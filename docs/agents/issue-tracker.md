# Issue-Tracker: GitHub

Issues und Specs dieses Repos liegen als GitHub Issues in `h1f1x/fidelius`. Alle Operationen laufen über die `gh` CLI; sie leitet das Repo im Klon selbst aus `git remote -v` ab.

## Konventionen

- **Issue anlegen**: `gh issue create --title "..." --body "..."`, mehrzeilige Bodies per Heredoc.
- **Issue lesen**: `gh issue view <nummer> --comments`, Kommentare mit `jq` filtern, Labels mit abrufen.
- **Issues auflisten**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`, dazu passende `--label`- und `--state`-Filter.
- **Kommentieren**: `gh issue comment <nummer> --body "..."`
- **Labels setzen / entfernen**: `gh issue edit <nummer> --add-label "..."` / `--remove-label "..."`
- **Schließen**: `gh issue close <nummer> --comment "..."`

## Pull Requests als Triage-Kanal

**PRs als Anfragekanal: nein.** _(Auf `ja` setzen, wenn externe PRs hier als Feature-Wünsche gelten; `/triage` liest diesen Schalter.)_

Bei `ja` laufen PRs durch dieselben Labels und Zustände wie Issues, mit den `gh pr`-Entsprechungen:

- **PR lesen**: `gh pr view <nummer> --comments`, den Diff mit `gh pr diff <nummer>`.
- **Externe PRs zur Triage auflisten**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`, dann nur `authorAssociation` mit `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR` oder `NONE` behalten.
- **Kommentieren / Labeln / Schließen**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

Issues und PRs teilen sich auf GitHub einen Nummernraum, ein `#42` kann beides sein: erst `gh pr view 42`, dann `gh issue view 42`.

## Wenn ein Skill „im Issue-Tracker veröffentlichen“ sagt

Ein GitHub Issue anlegen.

## Wenn ein Skill „das passende Ticket holen“ sagt

`gh issue view <nummer> --comments` ausführen.

## Wayfinding

Für `/wayfinder`. Die **Map** ist ein einzelnes Issue, die **Child-Tickets** hängen daran.

- **Map**: ein Issue mit Label `wayfinder:map`, im Body Notes / Decisions-so-far / Fog. `gh issue create --label wayfinder:map`.
- **Child-Ticket**: ein Issue, als GitHub Sub-Issue an die Map gehängt (`gh api` auf den Sub-Issues-Endpunkt). Wo Sub-Issues fehlen: das Child in eine Task-Liste im Map-Body aufnehmen und `Part of #<map>` an den Anfang des Child-Bodys setzen. Labels: `wayfinder:<typ>` (`research`/`prototype`/`grilling`/`task`). Wer ein Ticket übernimmt, wird Assignee.
- **Blockaden**: GitHubs **native Issue-Abhängigkeiten**, sichtbar in der UI. Kante anlegen mit `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`. `<blocker-db-id>` ist die numerische **Datenbank-ID** des Blockers (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`), weder `#nummer` noch `node_id`. `issue_dependencies_summary.blocked_by` zählt nur offene Blocker und ist damit das aktuelle Tor. Wo Abhängigkeiten fehlen: eine Zeile `Blocked by: #<n>, #<n>` an den Anfang des Child-Bodys. Ein Ticket ist frei, sobald alle Blocker geschlossen sind.
- **Frontier-Abfrage**: offene Children der Map auflisten (`gh issue list --state open`, eingegrenzt auf Sub-Issues bzw. Task-Liste der Map), alle mit offenem Blocker (`issue_dependencies_summary.blocked_by > 0` oder offenes Issue in der `Blocked by`-Zeile) oder mit Assignee verwerfen; das erste in Map-Reihenfolge gewinnt.
- **Übernehmen**: `gh issue edit <n> --add-assignee @me`, der erste Schreibzugriff der Session.
- **Abschließen**: `gh issue comment <n> --body "<antwort>"`, dann `gh issue close <n>`, dann einen Kontext-Verweis (Kern + Link) an Decisions-so-far der Map anhängen.
