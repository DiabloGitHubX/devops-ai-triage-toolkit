"""Read-only Kubernetes diagnostic operations for the MCP server."""

from datetime import UTC, datetime
from typing import Any

from config import DEFAULT_LOG_TAIL, Settings
from kubernetes import client
from kubernetes import config as kube_config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException
from safety import (
    SafetyError,
    bound_response,
    truncate_text,
    validate_container_name,
    validate_label_selector,
    validate_namespace,
    validate_resource_name,
    validate_tail_lines,
)
from urllib3.exceptions import HTTPError

MAX_LOG_FETCH_BYTES = 65536
MAX_EVENT_SCAN = 1000
EVENT_PAGE_SIZE = 100


class KubernetesToolError(RuntimeError):
    """A sanitized Kubernetes diagnostic error."""


def _api_error(exc: ApiException) -> KubernetesToolError:
    """Convert Kubernetes API errors into safe, actionable messages."""

    messages = {
        400: (
            "Invalid Kubernetes request or requested logs "
            "are unavailable. Check the pod and container state."
        ),
        401: ("Kubernetes authentication failed. Refresh the restricted kubeconfig."),
        403: "Kubernetes RBAC denied the requested operation.",
        404: "The requested Kubernetes resource was not found.",
        429: "Kubernetes API rate limit reached. Retry later.",
        500: "Kubernetes API encountered an internal error.",
        503: "Kubernetes API is temporarily unavailable.",
    }

    return KubernetesToolError(
        messages.get(
            exc.status,
            "Kubernetes API request failed.",
        )
    )


def _timestamp(value: datetime | None) -> str | None:
    """Convert a Kubernetes timestamp into ISO 8601 format."""

    return value.isoformat() if value else None


def _age_seconds(created: datetime | None) -> int | None:
    """Calculate resource age in seconds."""

    if created is None:
        return None

    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)

    return max(
        0,
        int((datetime.now(UTC) - created).total_seconds()),
    )


def _container_state(state: Any) -> dict[str, Any]:
    """Serialize a Kubernetes container state."""

    if state is None:
        return {"state": "Unknown"}

    if state.waiting is not None:
        return {
            "state": "Waiting",
            "reason": state.waiting.reason,
            "message": state.waiting.message,
        }

    if state.running is not None:
        return {
            "state": "Running",
            "started_at": _timestamp(state.running.started_at),
        }

    if state.terminated is not None:
        terminated = state.terminated

        return {
            "state": "Terminated",
            "reason": terminated.reason,
            "message": terminated.message,
            "exit_code": terminated.exit_code,
            "signal": terminated.signal,
            "started_at": _timestamp(terminated.started_at),
            "finished_at": _timestamp(terminated.finished_at),
        }

    return {"state": "Unknown"}


def _container_status(status: Any) -> dict[str, Any]:
    """Serialize current and previous container states."""

    return {
        "name": status.name,
        "image": status.image,
        "ready": status.ready,
        "restart_count": status.restart_count or 0,
        "current_state": _container_state(status.state),
        "last_state": _container_state(status.last_state),
    }


def _container_spec(container: Any) -> dict[str, Any]:
    """Return diagnostic container configuration without env values."""

    resources = container.resources

    return {
        "name": container.name,
        "image": container.image,
        "image_pull_policy": container.image_pull_policy,
        "resources": {
            "requests": (resources.requests or {} if resources else {}),
            "limits": (resources.limits or {} if resources else {}),
        },
    }


def _pod_summary(pod: Any) -> dict[str, Any]:
    """Return a compact pod health summary."""

    statuses = pod.status.container_statuses or []
    init_statuses = pod.status.init_container_statuses or []

    ready = sum(1 for status in statuses if status.ready)

    total = len(pod.spec.containers or [])

    restarts = sum(status.restart_count or 0 for status in [*statuses, *init_statuses])

    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "phase": pod.status.phase,
        "ready": f"{ready}/{total}",
        "restart_count": restarts,
        "age_seconds": _age_seconds(pod.metadata.creation_timestamp),
        "container_statuses": [_container_status(status) for status in statuses],
        "init_container_statuses": [
            _container_status(status) for status in init_statuses
        ],
    }


def _event_time(event: Any) -> datetime:
    """Determine the most recent available event timestamp."""

    series = getattr(event, "series", None)

    candidates = [
        getattr(series, "last_observed_time", None),
        event.last_timestamp,
        event.event_time,
        event.first_timestamp,
        event.metadata.creation_timestamp,
    ]

    for value in candidates:
        if value is not None:
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)

            return value

    return datetime.min.replace(tzinfo=UTC)


def _event_summary(event: Any) -> dict[str, Any]:
    """Serialize relevant Kubernetes event evidence."""

    involved = event.involved_object
    series = getattr(event, "series", None)

    return {
        "type": event.type,
        "reason": event.reason,
        "message": event.message,
        "count": (getattr(series, "count", None) or event.count or 1),
        "timestamp": _timestamp(_event_time(event)),
        "involved_object": {
            "kind": involved.kind,
            "name": involved.name,
            "namespace": involved.namespace,
        },
    }


class KubernetesTools:
    """Read-only Kubernetes tools with shared safety enforcement."""

    def __init__(
        self,
        settings: Settings,
        core_api: client.CoreV1Api | None = None,
    ) -> None:
        self.settings = settings
        self._api_client = None

        if core_api is not None:
            # Dependency injection for isolated unit tests.
            self.core_api = core_api
        else:
            self.core_api = self._connect()

    def _connect(self) -> client.CoreV1Api:
        """Load explicit credentials and verify ServiceAccount identity."""

        if not self.settings.kubeconfig_path.is_file():
            raise KubernetesToolError(
                "Restricted kubeconfig is missing. Run make env or make kubeconfig."
            )

        connected = False

        try:
            self._api_client = kube_config.new_client_from_config(
                config_file=str(self.settings.kubeconfig_path),
                context=self.settings.kubeconfig_context,
                persist_config=False,
            )

            configuration = self._api_client.configuration

            if not configuration.verify_ssl:
                raise KubernetesToolError(
                    "Insecure Kubernetes TLS configuration rejected."
                )

            auth_api = client.AuthenticationV1Api(self._api_client)

            review = auth_api.create_self_subject_review(
                body=client.V1SelfSubjectReview(
                    api_version="authentication.k8s.io/v1",
                    kind="SelfSubjectReview",
                ),
                _request_timeout=self.settings.request_timeout,
            )

            identity = review.status.user_info.username
            parts = identity.split(":")

            if (
                len(parts) != 4
                or parts[0] != "system"
                or parts[1] != "serviceaccount"
                or parts[2] not in self.settings.allowed_namespaces
                or parts[3] != "triage-reader"
            ):
                raise KubernetesToolError(
                    "Unexpected Kubernetes identity. "
                    "The triage-reader ServiceAccount is required."
                )

            groups = review.status.user_info.groups or []

            if "system:masters" in groups:
                raise KubernetesToolError("Privileged Kubernetes identity rejected.")

            core_api = client.CoreV1Api(self._api_client)

            connected = True

            return core_api

        except ApiException as exc:
            raise _api_error(exc) from None

        except (ConfigException, HTTPError, OSError, ValueError):
            raise KubernetesToolError(
                "Unable to initialize restricted Kubernetes access. "
                "Check credentials, context and cluster connectivity."
            ) from None

        finally:
            if not connected:
                self.close()

    def close(self) -> None:
        """Release the owned Kubernetes API client."""

        if self._api_client is not None:
            self._api_client.close()
            self._api_client = None

    def _namespace(self, namespace: str) -> str:
        """Enforce namespace authorization before API calls."""

        return validate_namespace(
            namespace,
            self.settings.allowed_namespaces,
        )

    def _request(
        self,
        operation: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a bounded Kubernetes API request."""

        try:
            return operation(
                _request_timeout=self.settings.request_timeout,
                **kwargs,
            )

        except ApiException as exc:
            raise _api_error(exc) from None

        except (HTTPError, OSError, TimeoutError):
            raise KubernetesToolError(
                "Kubernetes API connection failed or timed out."
            ) from None

    def _bound(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Enforce the final application payload size limit."""

        return bound_response(
            payload,
            self.settings.max_response_bytes,
        )

    def list_pods(
        self,
        namespace: str,
        label_selector: str | None = None,
    ) -> dict[str, Any]:
        """List pod health and container failure states."""

        namespace = self._namespace(namespace)
        label_selector = validate_label_selector(label_selector)

        response = self._request(
            self.core_api.list_namespaced_pod,
            namespace=namespace,
            label_selector=label_selector,
            limit=self.settings.max_pods,
        )

        pods = [_pod_summary(pod) for pod in response.items]

        truncated = bool(response.metadata and response.metadata._continue)

        return self._bound(
            {
                "namespace": namespace,
                "label_selector": label_selector,
                "count": len(pods),
                "truncated": truncated,
                "pods": pods,
            }
        )

    def _collect_events(
        self,
        namespace: str,
        field_selector: str | None = None,
    ) -> dict[str, Any]:
        """Collect bounded event pages and sort newest first."""

        events = []
        continuation = None

        while len(events) < MAX_EVENT_SCAN:
            page_limit = min(
                EVENT_PAGE_SIZE,
                MAX_EVENT_SCAN - len(events),
            )

            response = self._request(
                self.core_api.list_namespaced_event,
                namespace=namespace,
                field_selector=field_selector,
                limit=page_limit,
                _continue=continuation,
            )

            events.extend(response.items)

            continuation = response.metadata._continue if response.metadata else None

            if not continuation:
                break

            if not response.items:
                break

        events.sort(
            key=_event_time,
            reverse=True,
        )

        selected = events[: self.settings.max_events]

        return {
            "count": len(selected),
            "scanned_count": len(events),
            "scan_complete": not bool(continuation),
            "truncated": (bool(continuation) or len(events) > len(selected)),
            "events": [_event_summary(event) for event in selected],
        }

    def describe_pod(
        self,
        namespace: str,
        pod_name: str,
    ) -> dict[str, Any]:
        """Inspect pod status, resources and recent events."""

        namespace = self._namespace(namespace)

        pod_name = validate_resource_name(
            pod_name,
            "pod name",
        )

        pod = self._request(
            self.core_api.read_namespaced_pod,
            namespace=namespace,
            name=pod_name,
        )

        result = _pod_summary(pod)

        result.update(
            {
                "node_name": pod.spec.node_name,
                "reason": pod.status.reason,
                "message": pod.status.message,
                "conditions": [
                    {
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason,
                        "message": condition.message,
                        "last_transition_time": _timestamp(
                            condition.last_transition_time
                        ),
                    }
                    for condition in (pod.status.conditions or [])
                ],
                "containers": [
                    _container_spec(container)
                    for container in (pod.spec.containers or [])
                ],
                "init_containers": [
                    _container_spec(container)
                    for container in (pod.spec.init_containers or [])
                ],
                "owners": [
                    {
                        "kind": owner.kind,
                        "name": owner.name,
                    }
                    for owner in (pod.metadata.owner_references or [])
                ],
            }
        )

        try:
            result["recent_events"] = self._collect_events(
                namespace,
                field_selector=(f"involvedObject.uid={pod.metadata.uid}"),
            )

        except KubernetesToolError as exc:
            result["recent_events"] = {
                "error": str(exc),
                "events": [],
                "scan_complete": False,
            }

        return self._bound(result)

    def get_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        container: str | None = None,
        tail_lines: int = DEFAULT_LOG_TAIL,
        previous: bool = False,
    ) -> dict[str, Any]:
        """Retrieve bounded current or previous container logs."""

        namespace = self._namespace(namespace)

        pod_name = validate_resource_name(
            pod_name,
            "pod name",
        )

        tail_lines = validate_tail_lines(tail_lines)

        if container is not None:
            container = validate_container_name(container)

        if type(previous) is not bool:
            raise SafetyError("previous must be a boolean")

        fetch_limit = min(
            MAX_LOG_FETCH_BYTES,
            self.settings.max_response_bytes,
        )

        logs = self._request(
            self.core_api.read_namespaced_pod_log,
            namespace=namespace,
            name=pod_name,
            container=container,
            tail_lines=tail_lines,
            previous=previous,
            limit_bytes=fetch_limit,
            follow=False,
            timestamps=False,
        )

        if not isinstance(logs, str):
            raise KubernetesToolError("Kubernetes returned an unexpected log format.")

        # Leave space for metadata and JSON serialization.
        text_limit = max(
            1,
            self.settings.max_response_bytes // 2,
        )

        result = truncate_text(
            logs,
            text_limit,
            keep_tail=True,
        )

        return self._bound(
            {
                "namespace": namespace,
                "pod_name": pod_name,
                "container": container,
                "previous": previous,
                "requested_tail_lines": tail_lines,
                "fetch_limit_bytes": fetch_limit,
                "source_may_be_truncated": (len(logs.encode("utf-8")) >= fetch_limit),
                "logs": result["text"],
                "truncated": result["truncated"],
                "received_bytes": result["original_bytes"],
                "returned_bytes": result["returned_bytes"],
            }
        )

    def list_events(
        self,
        namespace: str,
        involved_object: str | None = None,
    ) -> dict[str, Any]:
        """Return recent Normal and Warning events."""

        namespace = self._namespace(namespace)
        field_selector = None

        if involved_object is not None:
            involved_object = validate_resource_name(
                involved_object,
                "involved object name",
            )

            field_selector = f"involvedObject.name={involved_object}"

        result = self._collect_events(
            namespace,
            field_selector,
        )

        return self._bound(
            {
                "namespace": namespace,
                "involved_object": involved_object,
                **result,
            }
        )
