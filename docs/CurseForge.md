# CurseForge texts

## Summary (one sentence)

Your character's personal adventure history: a chronicle of every milestone, automatic screenshots, route replay on the map, professions and stats, all in one window.

---

## Description

**Journey Forever** keeps a diary of your character while you play. Level-ups, quests, deaths, achievements, new zones and rare kills are recorded automatically. You can look back at all of it in one window that matches the game's own interface: a chronicle, your route on the world map, your professions and your statistics.

Everything is stored locally in your SavedVariables. The addon never sends anything to other players or the internet, and it has no ads.

### Chronicle
- Records level-ups, completed quests, deaths, achievements, newly discovered zones, rare enemies killed, dungeon bosses defeated, completed dungeons, professions learned, profession ranks trained and recipes learned.
- Every entry shows when it happened and where you were, grouped by day. Milestones stand out with a gold accent.
- Deaths name their cause from the game's death recap ("Killed by Hogger", "Drowned"); hover for the killing blow.
- Search by text or place, and filter by kind of entry (Shift-click to show only one kind).
- Two looks: a parchment "Book" page or the classic list.
- Click an entry to jump to that moment on the map.
- Entries that got a screenshot are marked; hover to see whether it was saved and its file name. Tick "Only with screenshot" to list just those.

### Automatic screenshots
- Takes a screenshot for level-ups, achievements, rare kills, completed dungeons and the first visit to a zone. Quest completions and deaths can be switched on as well; each kind has its own check box.
- A short configurable delay lets the moment play out (default 5 seconds), and an optional countdown appears on screen. The countdown is hidden before the picture is taken.
- The interface can be hidden for the screenshot and comes back right after: all of it, or all except the event's popup (such as the level-up banner). This also works in combat.
- A cooldown keeps several events from producing a burst of pictures. Events close together share one screenshot.
- Test it with `/fjshot test`.

### Map and route replay
- Your route is drawn on the game's own zone and continent maps (position every 2 seconds by default; standing still adds no points).
- You can zoom with the mouse wheel and drag to pan.
- The timeline under the map shows the zones you passed through and marks for level-ups, deaths, rare kills, achievements and new zones; click a mark to jump to it.
- Replay with play and pause and several speeds: the route is painted as you go and the marker glides along it. A filter per play session and a live view that follows you.
- Colour the route by character level, by session, or in one colour. "Last 15 minutes" shows only your latest steps.
- Pins show where things happened; milestones are gold, deaths show a skull.
- Inside dungeons the game provides no position, so those moments are shown at the dungeon entrance.

### Overview
- Your character's full name, level, the game's experience bar with rested XP, and gold.
- Statistics:
  - total played time;
  - number of sessions;
  - enemies killed and experience earned;
  - rare enemies, quests, deaths, achievements, discovered zones, bosses defeated, dungeons completed and known recipes.
- A 3D model of your character with all equipped gear in the game's item buttons (tooltips, Shift-click to link, Ctrl-click to try on).
- A graph of the last two hours of play: experience, kills, quests or gold, with values on hover.

### Professions
- All your professions with skill level and rank.
- Every known recipe, grouped by category, in the item's quality colour, with a search box.
- Recipes are captured when you open a profession window. Search filters in that window don't affect the result.

### All your characters
- A character chooser at the top of the window shows any character on your account, read-only: their overview, saved gear, chronicle, routes and professions.
- The window always opens on the character you are playing, and recording only ever happens for that character.

### Comfort
- German and English (switch in the settings or with `/fj lang de` / `/fj lang en`).
- A minimap button (can be hidden), plus the addon compartment menu.
- A settings page and a storage overview: the addon keeps a generous history and drops the oldest entries when a store is full.
- A diagnostics page shows which game features were found and confirmed on your client.

### Commands
- `/fj` or `/chronicle`: open or close the window
- `/fj help`: all commands
- `/fj status`, `/fj professions`, `/fj played`, `/fj diag on|off`, `/fj dungeon`
- `/fjshot test`: take a test screenshot

### Good to know
- Made for **WoW Forever**. Some game features may change while Forever develops; the diagnostics page shows what works on your client.
- Data is saved when you log out or type `/reload`.
- History in the game is limited so logins stay fast. Routes, for example, cover roughly the last 55 hours of movement.

---

## Beschreibung (Deutsch)

**Journey Forever** führt beim Spielen Tagebuch über deinen Charakter. Stufenaufstiege, Quests, Tode, Erfolge, neue Gebiete und besiegte seltene Gegner werden automatisch festgehalten. Alles kannst du in einem Fenster nachsehen, das aussieht wie die Oberfläche des Spiels: Chronik, deine Route auf der Weltkarte, deine Berufe und deine Statistiken.

Alles wird lokal in deinen SavedVariables gespeichert. Das Addon sendet nichts an andere Spieler oder ins Internet und zeigt keine Werbung.

### Chronik
- Hält Stufenaufstiege, abgeschlossene Quests, Tode, Erfolge, neu entdeckte Gebiete, besiegte seltene Gegner, besiegte Dungeon-Bosse, abgeschlossene Dungeons, erlernte Berufe, Berufsränge und gelernte Rezepte fest.
- Jeder Eintrag zeigt, wann und wo es passiert ist, nach Tagen gruppiert. Meilensteine heben sich golden ab.
- Tode nennen ihre Ursache aus dem Todesbericht des Spiels („Getötet von Hogger“, „Ertrunken“); mit der Maus darüber siehst du den tödlichen Treffer.
- Suche nach Text oder Ort und Filter nach Art des Eintrags (Shift-Klick zeigt nur eine Art).
- Zwei Ansichten: eine Pergamentseite im „Buch“-Stil oder die klassische Liste.
- Ein Klick auf einen Eintrag springt zu diesem Moment auf der Karte.
- Einträge mit Screenshot sind markiert; mit der Maus darüber siehst du, ob er gespeichert wurde, und den Dateinamen. „Nur mit Screenshot“ zeigt nur diese Einträge.

### Automatische Screenshots
- Macht Screenshots bei Stufenaufstiegen, Erfolgen, seltenen Gegnern, abgeschlossenen Dungeons und beim ersten Besuch eines Gebiets. Quests und Tode lassen sich zusätzlich einschalten; jede Art hat ein eigenes Häkchen.
- Eine kurze einstellbare Verzögerung (Standard 5 Sekunden) lässt den Moment wirken; ein Countdown auf dem Bildschirm ist zuschaltbar. Er wird vor der Aufnahme ausgeblendet.
- Die Oberfläche lässt sich für den Screenshot ausblenden und kommt gleich danach zurück: ganz oder bis auf das Popup des Ereignisses (etwa den Stufenaufstieg). Das geht auch im Kampf.
- Eine Abklingzeit verhindert eine Bilderflut. Ereignisse kurz hintereinander teilen sich einen Screenshot.
- Zum Ausprobieren: `/fjshot test`.

### Karte und Routen-Wiedergabe
- Deine Route erscheint auf den Gebiets- und Kontinentkarten des Spiels (Position standardmäßig alle 2 Sekunden; Stillstehen erzeugt keine Punkte).
- Mit dem Mausrad zoomen, ziehen zum Verschieben.
- Die Zeitleiste unter der Karte zeigt die durchquerten Gebiete und Marken für Stufenaufstiege, Tode, seltene Gegner, Erfolge und neue Gebiete; ein Klick auf eine Marke springt dorthin.
- Wiedergabe mit Abspielen, Pause und mehreren Geschwindigkeiten: Die Route wird beim Abspielen gezeichnet, die Markierung gleitet an ihr entlang. Dazu ein Filter pro Spielsitzung und eine Live-Ansicht, die dir folgt.
- Die Route lässt sich nach Charakterstufe, nach Sitzung oder einfarbig einfärben. „Letzte 15 Minuten“ zeigt nur deine letzten Wege.
- Stecknadeln zeigen, wo etwas passiert ist; Meilensteine sind golden, Tode zeigen einen Totenkopf.
- In Dungeons liefert das Spiel keine Position, daher werden diese Momente am Dungeon-Eingang gezeigt.

### Übersicht
- Voller Name deines Charakters, Stufe, die Erfahrungsleiste des Spiels mit Erholungsbonus und Gold.
- Statistiken:
  - gesamte Spielzeit;
  - Anzahl der Sitzungen;
  - getötete Gegner und gesammelte Erfahrung;
  - seltene Gegner, Quests, Tode, Erfolge, entdeckte Gebiete, besiegte Bosse, abgeschlossene Dungeons und bekannte Rezepte.
- 3D-Modell deines Charakters mit der gesamten angelegten Ausrüstung in den Gegenstandsfeldern des Spiels (Tooltips, Shift-Klick zum Verlinken, Strg-Klick zum Anprobieren).
- Ein Verlauf der letzten zwei Spielstunden: Erfahrung, Gegner, Quests oder Gold, mit Werten beim Überfahren.

### Berufe
- Alle Berufe mit Fertigkeit und Rang.
- Alle bekannten Rezepte nach Kategorie, in der Qualitätsfarbe des Gegenstands, mit Suche.
- Rezepte werden beim Öffnen eines Berufsfensters erfasst. Suchfilter in diesem Fenster ändern das Ergebnis nicht.

### Alle deine Charaktere
- Über die Charakterauswahl oben im Fenster siehst du jeden Charakter deines Accounts (nur lesen): Übersicht, gespeicherte Ausrüstung, Chronik, Routen und Berufe.
- Das Fenster öffnet immer mit dem Charakter, den du gerade spielst, und aufgezeichnet wird nur für ihn.

### Komfort
- Deutsch und Englisch (umschaltbar in den Einstellungen oder mit `/fj lang de` / `/fj lang en`).
- Minimap-Knopf (ausblendbar) und Eintrag im Addon-Menü.
- Einstellungsseite und Speicherübersicht: Das Addon behält einen großzügigen Verlauf und entfernt die ältesten Einträge, wenn ein Speicher voll ist.
- Eine Diagnoseseite zeigt, welche Spielfunktionen auf deinem Client gefunden und bestätigt wurden.

### Befehle
- `/fj` oder `/chronicle`: Fenster öffnen oder schließen
- `/fj help`: alle Befehle
- `/fj status`, `/fj professions`, `/fj played`, `/fj diag on|off`, `/fj dungeon`
- `/fjshot test`: Test-Screenshot

### Gut zu wissen
- Gemacht für **WoW Forever**. Manche Spielfunktionen können sich ändern, solange Forever weiterentwickelt wird; die Diagnoseseite zeigt, was auf deinem Client funktioniert.
- Gespeichert wird beim Ausloggen oder mit `/reload`.
- Der Verlauf im Spiel ist begrenzt, damit das Einloggen schnell bleibt. Routen umfassen zum Beispiel etwa die letzten 55 Stunden Bewegung.
