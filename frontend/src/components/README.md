# components

```
layout/        AppShell, Sidebar, TopBar, AiPanelRegion  — the three regions
common/        base states: skeleton, empty, error, offline; theme switcher
ui/            primitives, shadcn/ui themed to the locked palette
inbox/         email rows, list, filters                   phase 2
thread/        thread reader, message, quoted-text control phase 3
intelligence/  AiValue and the per-capability chips        phase 4
companion/     conversation surface                        phase 10
settings/      feature controls, connected accounts        phase 11
```

`intelligence/AiValue.tsx` is the one component every AI-derived value renders through,
carrying its evidence span. It lands in phase 4, before any agent exists, because retrofitting
provenance across finished screens is a refactor of all of them.
