"""Everything the gateway's routes work with, built once and shared by both listeners.

Routes change things only through the application services here, and read through the `read` port.
"""

from dataclasses import dataclass, field

from thursday_gateway.application.backup import BackupService
from thursday_gateway.application.control import TaskControl
from thursday_gateway.application.deletion import DeletionSaga
from thursday_gateway.application.devices import DeviceService
from thursday_gateway.application.hub import Hub
from thursday_gateway.application.ingest import EventIngest
from thursday_gateway.application.ports import MainAgent, MetricsHistory, ReadQueries, VoiceAgent
from thursday_gateway.application.projects import ProjectService
from thursday_gateway.application.relay import MessageRelay
from thursday_gateway.application.retention import Retention
from thursday_gateway.application.status import DependencyStatus


@dataclass
class Services:
    projects: ProjectService
    relay: MessageRelay
    control: TaskControl
    deletion: DeletionSaga
    status: DependencyStatus
    devices: DeviceService  # one instance for both listeners: pairing codes and revocation signals live in it
    ingest: EventIngest
    retention: Retention
    read: ReadQueries
    main: MainAgent
    hub: Hub
    metrics: MetricsHistory | None = None
    metrics_hub: Hub = field(default_factory=Hub)
    backup: BackupService | None = None
    voice: VoiceAgent | None = None
