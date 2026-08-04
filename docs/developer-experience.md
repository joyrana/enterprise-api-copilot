# Developer Experience

This project standardizes daily engineering practices.

## Architecture

- System and domain references: [architecture.md](architecture.md)
- Decisions: [adr/](adr/)

## Coding Standards

- Backend, frontend, and Python conventions: [coding-standards.md](coding-standards.md)

## Development Workflow

- Create feature branch
- Implement with tests
- Run local checks
- Open PR with context and risks

## Branching Strategy

- `main` is always releasable
- `feature/*`, `fix/*`, `chore/*` for short-lived branches

## Commit Convention

- Use conventional commits when possible (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`)

## Release Strategy

- Milestone-aligned releases tracked in [milestones.md](milestones.md)
- Semantic version progression to `v1.0`
