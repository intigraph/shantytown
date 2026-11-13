"""Resolve a declared off-host lead without projecting a local lifecycle card."""
from .files import FilesRegistry


class _WithLead:
    def __init__(self, local, lead):
        self.local, self.lead = local, lead
        self.remote_lead = lead.name

    def get(self, name):
        if name == self.lead.name:
            return self.lead
        return self.local.get(name)

    def all(self):
        # Local administrator discovery and lifecycle enumeration stay local.
        return self.local.all()

    def __getattr__(self, name):
        return getattr(self.local, name)


def with_remote_lead(registry, worker, root):
    """One command-scoped graph read, only for a missing declared lead.

    Offline deployments do not acquire a graph dependency. An absent local
    projection remains an error; only explicit placement on another host admits
    the graph identity. Backend failures propagate rather than changing leads.
    """
    if root is None or not isinstance(registry, FilesRegistry):
        return registry
    name = registry.get(worker).reports_to
    if not name:
        return registry
    try:
        registry.get(name)
        return registry
    except LookupError:
        from .deployment import deployment_default, local_host
        host = local_host(root)
        if not host or not deployment_default(root, "QUIPU_SERVER"):
            raise
        from .quipu import QuipuRegistry
        lead = QuipuRegistry(root=root).get(name)
        if not lead.host or lead.host == host:
            raise LookupError(f"{name} has no off-host placement; sync local cards first")
        return _WithLead(registry, lead)
