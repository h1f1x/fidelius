# Domain-Doku

Wie die Engineering-Skills die Domain-Doku dieses Repos beim Erkunden des Codes nutzen.

## Vor dem Erkunden lesen

- **`CONTEXT.md`** im Repo-Root: das Glossar.
- **`docs/adr/`**: die ADRs, die den Bereich berühren, in dem gleich gearbeitet wird.

Fehlt eine dieser Dateien, geht die Arbeit einfach weiter. Angelegt werden sie erst bei Bedarf, durch `/domain-modeling` (erreichbar über `/grill-with-docs` und `/improve-codebase-architecture`), sobald ein Begriff oder eine Entscheidung tatsächlich geklärt ist.

## Dateistruktur

Single-context:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-….md
│   └── 0002-….md
└── app/
```

## Begriffe aus dem Glossar verwenden

Wo eine Ausgabe ein Domain-Konzept benennt (Issue-Titel, Refactoring-Vorschlag, Hypothese, Testname), steht der Begriff so, wie `CONTEXT.md` ihn definiert, und nicht ein Synonym, das das Glossar ausdrücklich vermeidet.

Fehlt ein benötigter Begriff im Glossar, ist das ein Signal: Entweder entsteht gerade Sprache, die das Projekt nicht nutzt (überdenken), oder es gibt eine echte Lücke (für `/domain-modeling` notieren).

## Widersprüche zu ADRs offenlegen

Widerspricht eine Ausgabe einem bestehenden ADR, steht das ausdrücklich dabei:

> _Widerspricht ADR-0007 (…), lohnt sich aber neu aufzurollen, weil …_
