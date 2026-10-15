# 0001: Klassifikation warnt nach den Regeln der Installation und bewertet den anonymisierten Text

Stand: 2026-10-15. Status: angenommen. Spec: [docs/specs/klassifikation.md](../specs/klassifikation.md).

## Kontext

Organisationen teilen ihre Informationen in Schutzstufen ein und legen je Stufe fest, ob sie in ein KI-System dürfen. Die Stufen, ihre Namen und ihre Regeln unterscheiden sich von Organisation zu Organisation und sind oft selbst nicht öffentlich. Fidelius ist öffentlicher Code.

Fidelius ersetzt Namen, Kontaktdaten und Kennungen. Ein Text kann danach trotzdem sensibel bleiben: Ein Geschäftsgeheimnis, ein Schwachstellenbericht oder eine Diagnose verlieren ihren Schutzbedarf nicht dadurch, dass die Namen fehlen.

Die Einschätzung kommt von Laya, also von einem Modell. Es irrt sich in beide Richtungen.

## Entscheidung

1. **Die Regeln kommen aus der Installation.** Stufen, Kurzbeschreibungen für Laya, Anzeigetexte und die Freigabegrenze stehen in `local/klassifikation.yaml` außerhalb des Repos. Der Code setzt keine bestimmte Stufe voraus. Das Repo enthält nur ein generisches Beispiel.
2. **Fidelius warnt, es sperrt nicht.** Liegt eine Stufe über der Freigabe oder enthält der Text Zugangsdaten, erscheint ein Warnbanner. Kopieren und Weitergeben bleiben möglich.
3. **Bewertet wird das Original und der anonymisierte Text.** Maßgeblich für die Regel zur KI-Nutzung ist der anonymisierte Text, denn er geht in das KI-System. Das Original zeigt, was die Anonymisierung bewirkt hat.
4. **Ein Feature-Flag je Installation schaltet die Funktion ein.** `CLASSIFICATION_ENABLED`, Standard aus. Aktiv ist sie nur bei Flag an und gültiger Regeldatei. Aus heißt vollständig aus, einschließlich der Zugangsdaten-Erkennung. Nutzer können sie nicht selbst abschalten.

## Begründung

- Zu 1: Nur so kann dieselbe Software in mehreren Organisationen laufen, ohne dass deren Regeln öffentlich werden.
- Zu 2: Eine Sperre auf Grundlage eines Modells erzeugt Fehlalarme, um die Nutzer herumarbeiten. Klassifikationsregeln sehen zudem häufig Ausnahmen nach Einzelfallfreigabe vor, die Fidelius nicht kennen kann. Eine Warnung lässt die Entscheidung bei der Person, die die Freigabe hat.
- Zu 3: Nur die Bewertung des anonymisierten Texts deckt auf, wo Platzhalter nicht reichen.
- Zu 4: Ein Flag, das „aus“ als den Stand vor der Klassifikation garantiert, ist ein sicherer Rückweg, falls die Einschätzungen im Betrieb nicht tragen. Getrennt von der Datei lässt es sich auch schalten, ohne die Regeln anzufassen, und ein Flag ohne Datei fällt in `/api/health` auf. Eine Warnung, die Nutzer selbst abschalten können, verfehlt ihren Zweck.

## Folgen

- Fehlt das Flag oder `local/klassifikation.yaml`, gibt es keine Klassifikation. Eine Installation muss beides aktiv einrichten.
- Der Code trägt zwei Pfade, Tests laufen mit beiden Flag-Stellungen.
- Die Treffsicherheit hängt an den Kurzbeschreibungen der Installation. Jede Installation sollte sie mit eigenen Beispielen messen (`scripts/run_classification.py`).
- Der anonymisierte Text kostet einen zweiten Laya-Durchlauf je Analyse.
- Weil nicht gesperrt wird, kann ein Text über der Freigabe Fidelius verlassen. Die Verantwortung bleibt bei der Person, die ihn kopiert. Die Infobox sagt das ausdrücklich.
