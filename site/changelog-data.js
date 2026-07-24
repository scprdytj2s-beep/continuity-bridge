// ── Changelog data ───────────────────────────────────────────────────────────
// Nieuwe versie toevoegen? Plaats één object bovenaan deze array.
// Zet latest: true op de nieuwste; verwijder latest bij de vorige.
// kind: 'new' | 'improve' | 'fix'  →  label + kleur worden automatisch bepaald.

const RELEASES = [
  {
    version: 'v1.4.0',
    date: { nl: '24 juli 2026', en: '24 July 2026', de: '24. Juli 2026' },
    latest: true,
    title: {
      nl: '.avb-bin direct inslepen & duidelijkere PU/AFG',
      en: 'Direct .avb bin drop & clearer PU/AFG',
      de: 'Direktes .avb-Bin-Ziehen & klarere PU/AFG',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Avid .avb-bin direct inslepen</strong> — naast een ALE-export kan je nu ook meteen het .avb-bin bestand zelf gebruiken',
            en: '<strong>Drag in an Avid .avb bin directly</strong> — besides an ALE export you can now also use the .avb bin file itself',
            de: '<strong>Avid-.avb-Bin direkt hineinziehen</strong> — neben einem ALE-Export kannst du jetzt auch direkt die .avb-Bin-Datei verwenden',
          },
          {
            nl: '<strong>Keuzedialoog bij dubbelzinnige takes</strong> — bij twijfelachtige scene/slate-matches verschijnt nu een blokkerend venster (voorheen alleen bij .avb, nu ook bij ALE), met een knop om direct de betreffende PDF-pagina te openen',
            en: '<strong>Choice dialog for ambiguous takes</strong> — a blocking window now appears for uncertain scene/slate matches (previously only for .avb, now also for ALE), with a button to open the relevant PDF page directly',
            de: '<strong>Auswahldialog bei mehrdeutigen Takes</strong> — bei unsicheren Szenen/Slate-Treffern erscheint jetzt ein blockierendes Fenster (bisher nur bei .avb, jetzt auch bei ALE), mit einer Schaltfläche zum direkten Öffnen der betreffenden PDF-Seite',
          },
          {
            nl: '<strong>AFG in eigen kolom</strong> wegschrijven — analoog aan de bestaande PU-optie',
            en: 'Write <strong>AFG to its own column</strong> — analogous to the existing PU option',
            de: '<strong>AFG in eigene Spalte</strong> schreiben — analog zur bestehenden PU-Option',
          },
          {
            nl: '<strong>"Naam" als doelkolom</strong> voor PU/AFG — de markering komt dan direct achter de takenaam, bijv. <em>01-46_064-05 (AFG)</em>',
            en: '<strong>"Name" as target column</strong> for PU/AFG — the marker is then appended directly after the take name, e.g. <em>01-46_064-05 (AFG)</em>',
            de: '<strong>"Name" als Zielspalte</strong> für PU/AFG — die Markierung wird dann direkt an den Take-Namen angehängt, z. B. <em>01-46_064-05 (AFG)</em>',
          },
          {
            nl: '<strong>Uitleg-bubbels (hover)</strong> bij de PU/AFG-instellingen in Voorkeuren — inclusief duidelijke uitleg dat "Auto" dezelfde kolom gebruikt als hierboven gekozen voor Notes',
            en: '<strong>Hover tooltips</strong> for the PU/AFG settings in Preferences — including a clear explanation that "Auto" uses the same column chosen for Notes above',
            de: '<strong>Hover-Tooltips</strong> bei den PU/AFG-Einstellungen in den Einstellungen — inklusive klarer Erklärung, dass "Auto" dieselbe Spalte wie oben bei Notizen verwendet',
          },
          {
            nl: '<strong>Strakker uiterlijk</strong>, iets meer richting Avid Link — neutralere grijstinten, vlakkere knoppen en ronde badges',
            en: '<strong>Tighter look</strong>, closer to Avid Link — more neutral gray tones, flatter buttons and round badges',
            de: '<strong>Schlankeres Erscheinungsbild</strong>, näher an Avid Link — neutralere Grautöne, flachere Schaltflächen und runde Badges',
          },
        ],
      },
      {
        kind: 'fix',
        items: [
          {
            nl: 'Continuïteitsrapporten: de <strong>AF-kolom</strong> (afgebroken take) werd nooit gelezen — wordt nu correct herkend',
            en: 'Continuity reports: the <strong>AF column</strong> (aborted take) was never read — now recognized correctly',
            de: 'Continuity-Berichte: die <strong>AF-Spalte</strong> (abgebrochener Take) wurde nie gelesen — wird jetzt korrekt erkannt',
          },
          {
            nl: 'Continuïteitsrapporten: een <strong>underscore</strong> tussen scene en slate (bijv. <em>02-34_048-03</em>) werd niet herkend — werkt nu naast het streepje',
            en: 'Continuity reports: an <strong>underscore</strong> between scene and slate (e.g. <em>02-34_048-03</em>) was not recognized — now works alongside the hyphen',
            de: 'Continuity-Berichte: ein <strong>Unterstrich</strong> zwischen Szene und Slate (z. B. <em>02-34_048-03</em>) wurde nicht erkannt — funktioniert jetzt neben dem Bindestrich',
          },
          {
            nl: 'Continuïteitsrapporten: notities na slate 16 werden overgeslagen — opgelost',
            en: 'Continuity reports: notes after slate 16 were skipped — fixed',
            de: 'Continuity-Berichte: Notizen nach Slate 16 wurden übersprungen — behoben',
          },
          {
            nl: '<strong>Kolom-kiezer</strong>: op Annuleren klikken zette per ongeluk een placeholder-kolom ("Kies kolom...") in de export — opgelost',
            en: '<strong>Column picker</strong>: clicking Cancel accidentally left a placeholder column ("Choose column...") in the export — fixed',
            de: '<strong>Spaltenauswahl</strong>: Klick auf Abbrechen hinterließ versehentlich eine Platzhalter-Spalte ("Spalte wählen...") im Export — behoben',
          },
          {
            nl: 'Diverse crashfixes bij opstarten (o.a. zwart venster) en in de layout-mapper voor onherkende PDF-formaten',
            en: 'Various startup crash fixes (including a black window) and in the layout mapper for unrecognized PDF formats',
            de: 'Verschiedene Absturz-Fixes beim Start (u. a. schwarzes Fenster) und im Layout-Mapper für unerkannte PDF-Formate',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.9.2',
    date: { nl: '15 juli 2026', en: '15 July 2026', de: '15. Juli 2026' },
    title: {
      nl: 'Updater gerepareerd & ALE-codering',
      en: 'Updater fixed & ALE encoding',
      de: 'Updater repariert & ALE-Codierung',
    },
    groups: [
      {
        kind: 'fix',
        items: [
          {
            nl: '<strong>In-app updater gerepareerd</strong> — de "Update &amp; Herstart"-knop die bleef hangen (draaiend balletje, lege voortgangsbalk) is definitief opgelost. Let op: wie op een oudere versie zit moet deze update éénmalig nog handmatig downloaden; vanaf v1.3.9.2 werkt updaten voortaan direct vanuit de app.',
            en: '<strong>In-app updater fixed</strong> — the "Update &amp; Restart" button that hung (spinning wheel, empty progress bar) is now permanently resolved. Note: if you\'re on an older version you need to download this update manually once; from v1.3.9.2 onward updating works directly from the app.',
            de: '<strong>In-App-Updater repariert</strong> — die "Aktualisieren &amp; Neustarten"-Schaltfläche, die hängen blieb (drehendes Rädchen, leerer Fortschrittsbalken), ist jetzt endgültig behoben. Hinweis: Wer eine ältere Version nutzt, muss dieses Update einmalig manuell herunterladen; ab v1.3.9.2 funktioniert das Aktualisieren direkt aus der App.',
          },
          {
            nl: 'FAQ bijgewerkt met de juiste <strong>macOS Sequoia</strong>-instructies voor het openen van de app.',
            en: 'FAQ updated with the correct <strong>macOS Sequoia</strong> instructions for opening the app.',
            de: 'FAQ mit den richtigen <strong>macOS-Sequoia</strong>-Anweisungen zum Öffnen der App aktualisiert.',
          },
        ],
      },
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Nieuwe instelling "ALE-codering"</strong> (Auto / UTF-8 / Mac Roman) — lost het umlaut-probleem definitief op. Werk je met een oudere Avid (zonder UTF-8-optie bij ALE-export)? Zet \'m dan op Mac Roman.',
            en: '<strong>New "ALE encoding" setting</strong> (Auto / UTF-8 / Mac Roman) — permanently solves the umlaut issue. Using an older Avid (without a UTF-8 option on ALE export)? Set it to Mac Roman.',
            de: '<strong>Neue Einstellung "ALE-Codierung"</strong> (Auto / UTF-8 / Mac Roman) — behebt das Umlaut-Problem endgültig. Nutzt du ein älteres Avid (ohne UTF-8-Option beim ALE-Export)? Dann stelle sie auf Mac Roman.',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.9.1',
    date: { nl: '6 juli 2026', en: '6 July 2026', de: '6. Juli 2026' },
    title: {
      nl: 'Take-herkenning LockitNetwork',
      en: 'Take recognition LockitNetwork',
      de: 'Take-Erkennung LockitNetwork',
    },
    groups: [
      {
        kind: 'fix',
        items: [
          {
            nl: 'Opgelost: in <strong>LockitNetwork</strong>-rapporten kon een take-regel de volgende take "opslokken", waardoor die take (inclusief rating) niet doorkwam. Alle takes worden nu correct herkend.',
            en: 'Fixed: in <strong>LockitNetwork</strong> reports a take line could "swallow" the next take, causing that take (including its rating) to be dropped. All takes are now recognized correctly.',
            de: 'Behoben: in <strong>LockitNetwork</strong>-Berichten konnte eine Take-Zeile den nächsten Take "verschlucken", sodass dieser Take (samt Bewertung) nicht übernommen wurde. Alle Takes werden jetzt korrekt erkannt.',
          },
          {
            nl: 'Tijdcodes in take-opmerkingen worden genegeerd; de eventuele tekst erna komt gewoon door.',
            en: 'Timecodes in take notes are ignored; any text after them still comes through.',
            de: 'Timecodes in Take-Notizen werden ignoriert; ein eventueller Text danach wird trotzdem übernommen.',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.9',
    date: { nl: '6 juli 2026', en: '6 July 2026', de: '6. Juli 2026' },
    title: {
      nl: 'Uiterlijk-instellingen & Scene-kolom',
      en: 'Appearance settings & Scene column',
      de: 'Darstellungs-Einstellungen & Szenen-Spalte',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Scene-doelkolom instelbaar</strong> (Uit / Auto / eigen kolom) — behoud je originele Scene-data',
            en: '<strong>Configurable scene target column</strong> (Off / Auto / own column) — keep your original Scene data',
            de: '<strong>Einstellbare Szenen-Zielspalte</strong> (Aus / Auto / eigene Spalte) — behalte deine originalen Szenendaten',
          },
          {
            nl: '<strong>Nieuwe "Uiterlijk"-instellingen</strong> — interfacegrootte-schuif (10–200%), lettertypekeuze en accentkleur, passen direct toe',
            en: '<strong>New "Appearance" settings</strong> — interface size slider (10–200%), font choice and accent color, applied instantly',
            de: '<strong>Neue "Darstellung"-Einstellungen</strong> — Schieberegler für die Oberflächengröße (10–200%), Schriftwahl und Akzentfarbe, sofort angewendet',
          },
          {
            nl: '<strong>Optie map niet openen</strong> na verwerken; optionele umlaut-omzetting (ü→ue, ö→oe, ä→ae, ß→ss)',
            en: '<strong>Option to not open the folder</strong> after processing; optional umlaut conversion (ü→ue, ö→oe, ä→ae, ß→ss)',
            de: '<strong>Option, den Ordner nicht zu öffnen</strong> nach der Verarbeitung; optionale Umlaut-Umwandlung (ü→ue, ö→oe, ä→ae, ß→ss)',
          },
        ],
      },
      {
        kind: 'improve',
        items: [
          {
            nl: 'Duitse tekens/umlauten blijven correct bij import — ALE wordt in dezelfde codering teruggeschreven als de export',
            en: 'German characters/umlauts stay correct on import — the ALE is written back in the same encoding as the export',
            de: 'Deutsche Zeichen/Umlaute bleiben beim Import korrekt — die ALE wird in derselben Codierung zurückgeschrieben wie beim Export',
          },
          {
            nl: 'Overzichtelijkere Voorkeuren — in/uitklapbare secties met scrollbalk, apart "Uitvoer"-hoofdstuk',
            en: 'Clearer Preferences — collapsible sections with a scrollbar, a separate "Output" chapter',
            de: 'Übersichtlichere Einstellungen — ein-/ausklappbare Abschnitte mit Scrollbalken, ein separates Kapitel "Ausgabe"',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.8',
    date: { nl: '12 juni 2026', en: '12 June 2026', de: '12. Juni 2026' },
    title: {
      nl: 'Scene-kolom & Duitse tekens',
      en: 'Scene column & German characters',
      de: 'Szenen-Spalte & deutsche Zeichen',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Scene-doelkolom instelbaar</strong> — kies of CB scene-info in bestaande Scene-kolom schrijft, in eigen kolom, of helemaal niet',
            en: '<strong>Configurable scene target column</strong> — choose whether CB writes scene info into the existing Scene column, into its own column, or not at all',
            de: '<strong>Einstellbare Szenen-Zielspalte</strong> — wähle, ob CB die Szeneninfo in die vorhandene Szenen-Spalte, in eine eigene Spalte oder gar nicht schreibt',
          },
          {
            nl: '<strong>Volledig meertalig label</strong> — het "{originele naam}"-veld bij Bestandsnaam volgt nu de gekozen taal (NL/EN/DE)',
            en: '<strong>Fully multilingual label</strong> — the "{original name}" field under Filename now follows the selected language (NL/EN/DE)',
            de: '<strong>Vollständig mehrsprachiges Label</strong> — das Feld "{Originalname}" beim Dateinamen folgt jetzt der gewählten Sprache (NL/EN/DE)',
          },
        ],
      },
      {
        kind: 'improve',
        items: [
          {
            nl: 'Correcte weergave van accenten en umlauten — Duitse en speciale tekens (ä ö ü Ä Ö Ü, etc.) blijven intact bij import in Avid (UTF-8 output)',
            en: 'Correct display of accents and umlauts — German and special characters (ä ö ü Ä Ö Ü, etc.) stay intact when imported into Avid (UTF-8 output)',
            de: 'Korrekte Darstellung von Akzenten und Umlauten — deutsche und Sonderzeichen (ä ö ü Ä Ö Ü usw.) bleiben beim Import in Avid erhalten (UTF-8-Ausgabe)',
          },
          {
            nl: 'Betrouwbaardere in-app update — "Update & Herstart" vervangt app nu veilig na afsluiten i.p.v. tijdens het draaien',
            en: 'More reliable in-app update — "Update & Restart" now safely replaces the app after closing instead of while running',
            de: 'Zuverlässigeres In-App-Update — "Aktualisieren & Neustarten" ersetzt die App jetzt sicher nach dem Beenden statt während des Betriebs',
          },
          {
            nl: 'Grotere lettergrootte in het hoofdvenster voor betere leesbaarheid',
            en: 'Larger font size in the main window for better readability',
            de: 'Größere Schriftgröße im Hauptfenster für bessere Lesbarkeit',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.7',
    date: { nl: '9 juni 2026', en: '9 June 2026', de: '9. Juni 2026' },
    title: {
      nl: 'Schonere ALE-export & betere FAQ',
      en: 'Cleaner ALE export & better FAQ',
      de: 'Saubererer ALE-Export & bessere FAQ',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Ontbrekende Tracks-kolom</strong> wordt automatisch toegevoegd',
            en: '<strong>Missing Tracks column</strong> is added automatically',
            de: '<strong>Fehlende Tracks-Spalte</strong> wird automatisch hinzugefügt',
          },
          {
            nl: '<strong>Optie "Wissen na verwerken"</strong> — Uit / Vragen / Automatisch, met instelbare vertraging',
            en: '<strong>"Clear after processing" option</strong> — Off / Ask / Automatic, with adjustable delay',
            de: '<strong>Option "Nach Verarbeitung löschen"</strong> — Aus / Fragen / Automatisch, mit einstellbarer Verzögerung',
          },
          {
            nl: '<strong>Kolomnamen vrij invulbaar</strong> in Voorkeuren',
            en: '<strong>Freely editable column names</strong> in Preferences',
            de: '<strong>Frei editierbare Spaltennamen</strong> in den Einstellungen',
          },
          {
            nl: '<strong>Vernieuwde FAQ</strong> met nieuwe onderwerpen (ALE exporteren uit Avid, uitleg over "Merge?"-melding) en directe link naar bugrapport',
            en: '<strong>Revamped FAQ</strong> with new topics (exporting ALE from Avid, explanation of the "Merge?" prompt) and a direct link to the bug report',
            de: '<strong>Überarbeitete FAQ</strong> mit neuen Themen (ALE aus Avid exportieren, Erklärung zur "Merge?"-Meldung) und direktem Link zum Fehlerbericht',
          },
        ],
      },
      {
        kind: 'improve',
        items: [
          {
            nl: 'Lege camera- en metadatakolommen worden automatisch verwijderd — elimineert Avid-importfouten ("syntax error in timecode field" / "invalid tracks")',
            en: 'Empty camera and metadata columns are removed automatically — eliminates Avid import errors ("syntax error in timecode field" / "invalid tracks")',
            de: 'Leere Kamera- und Metadatenspalten werden automatisch entfernt — verhindert Avid-Importfehler ("syntax error in timecode field" / "invalid tracks")',
          },
          {
            nl: 'Rating-kolom wordt automatisch opgeschoond, alleen jouw V/X-waarden blijven',
            en: 'Rating column is cleaned up automatically, leaving only your V/X values',
            de: 'Bewertungsspalte wird automatisch bereinigt, nur deine V/X-Werte bleiben',
          },
          {
            nl: 'Notitiekolom wordt netjes afgehandeld — geen import-problemen meer met Take_notes',
            en: 'Notes column is handled cleanly — no more import issues with Take_notes',
            de: 'Notizspalte wird sauber verarbeitet — keine Importprobleme mehr mit Take_notes',
          },
          {
            nl: 'Diverse verbeteringen aan leesbaarheid en interface',
            en: 'Various readability and interface improvements',
            de: 'Verschiedene Verbesserungen an Lesbarkeit und Oberfläche',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.6',
    date: { nl: '9 juni 2026', en: '9 June 2026', de: '9. Juni 2026' },
    title: {
      nl: 'Intel-Mac support & Unicode handling',
      en: 'Intel Mac support & Unicode handling',
      de: 'Intel-Mac-Unterstützung & Unicode-Handling',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>PU als eigen kolom</strong> wegschrijven',
            en: 'Write <strong>PU as its own column</strong>',
            de: '<strong>PU als eigene Spalte</strong> schreiben',
          },
        ],
      },
      {
        kind: 'improve',
        items: [
          {
            nl: 'Drag-and-drop werkt nu ook op <strong>Intel-Macs</strong> (en Silicon)',
            en: 'Drag-and-drop now works on <strong>Intel Macs</strong> too (and Silicon)',
            de: 'Drag-and-drop funktioniert jetzt auch auf <strong>Intel-Macs</strong> (und Silicon)',
          },
          {
            nl: 'Veilige verwerking van speciale tekens (<strong>Unicode</strong>) in ALE\'s',
            en: 'Safe handling of special characters (<strong>Unicode</strong>) in ALEs',
            de: 'Sichere Verarbeitung von Sonderzeichen (<strong>Unicode</strong>) in ALEs',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.5',
    date: { nl: '4 juni 2026', en: '4 June 2026', de: '4. Juni 2026' },
    title: {
      nl: 'Meertalig & Duitse editor-logs',
      en: 'Multilingual & German editor logs',
      de: 'Mehrsprachig & deutsche Editor-Logs',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Meertalig</strong> — Nederlands, Engels en Duits (instelbaar via Voorkeuren)',
            en: '<strong>Multilingual</strong> — Dutch, English and German (set in Preferences)',
            de: '<strong>Mehrsprachig</strong> — Niederländisch, Englisch und Deutsch (in den Einstellungen wählbar)',
          },
          {
            nl: '<strong>Duitse editors-log</strong> rapportformaat ondersteund',
            en: '<strong>German editor log</strong> report format supported',
            de: '<strong>Deutsches Editor-Log</strong>-Berichtsformat unterstützt',
          },
          {
            nl: '<strong>Rating als letters</strong> (A/B/C/D/E) als extra optie naast sterren',
            en: '<strong>Rating as letters</strong> (A/B/C/D/E) as an extra option alongside stars',
            de: '<strong>Bewertung als Buchstaben</strong> (A/B/C/D/E) als zusätzliche Option neben Sternen',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.4',
    date: { nl: '4 juni 2026', en: '4 June 2026', de: '4. Juni 2026' },
    title: { nl: 'Update dialog fix', en: 'Update dialog fix', de: 'Update-Dialog-Fix' },
    groups: [
      {
        kind: 'fix',
        items: [
          {
            nl: 'Knop in update-dialoogvenster was niet klikbaar op <strong>Canvas</strong> — opgelost',
            en: 'Button in the update dialog was not clickable on <strong>Canvas</strong> — fixed',
            de: 'Schaltfläche im Update-Dialog war auf <strong>Canvas</strong> nicht klickbar — behoben',
          },
          {
            nl: 'Bevat alle fixes uit v1.3.3',
            en: 'Includes all fixes from v1.3.3',
            de: 'Enthält alle Fixes aus v1.3.3',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.3',
    date: { nl: '4 juni 2026', en: '4 June 2026', de: '4. Juni 2026' },
    title: {
      nl: 'Stabiliteit & parsing fixes',
      en: 'Stability & parsing fixes',
      de: 'Stabilitäts- & Parsing-Fixes',
    },
    groups: [
      {
        kind: 'fix',
        items: [
          {
            nl: 'Crash in NSMenuItem bij bepaalde menu-interacties opgelost',
            en: 'Crash in NSMenuItem during certain menu interactions fixed',
            de: 'Absturz in NSMenuItem bei bestimmten Menü-Interaktionen behoben',
          },
          {
            nl: '<strong>Take 4-parsing</strong> met non-ASCII tekens werkt nu correct',
            en: '<strong>Take 4 parsing</strong> with non-ASCII characters now works correctly',
            de: '<strong>Take-4-Parsing</strong> mit Nicht-ASCII-Zeichen funktioniert jetzt korrekt',
          },
          {
            nl: 'Drag & drop toont nu een duidelijkere foutmelding als het bestand niet herkend wordt',
            en: 'Drag & drop now shows a clearer error message when a file is not recognized',
            de: 'Drag & Drop zeigt jetzt eine klarere Fehlermeldung, wenn eine Datei nicht erkannt wird',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.2',
    date: { nl: '4 juni 2026', en: '4 June 2026', de: '4. Juni 2026' },
    title: { nl: 'Stabiliteitsfixes', en: 'Stability fixes', de: 'Stabilitäts-Fixes' },
    groups: [
      {
        kind: 'fix',
        items: [
          {
            nl: 'SSL-certificaatfout bij update-check op <strong>Intel Macs</strong> opgelost',
            en: 'SSL certificate error during update check on <strong>Intel Macs</strong> fixed',
            de: 'SSL-Zertifikatfehler bei der Update-Prüfung auf <strong>Intel-Macs</strong> behoben',
          },
          {
            nl: 'Extra continuïteitsrapport-formaten (o.a. <strong>D&N</strong>) worden nu correct herkend',
            en: 'Additional continuity report formats (including <strong>D&N</strong>) are now recognized correctly',
            de: 'Zusätzliche Continuity-Berichtsformate (u. a. <strong>D&N</strong>) werden jetzt korrekt erkannt',
          },
          {
            nl: 'Kolomnamen zijn niet meer hoofdlettergevoelig — <strong>Notes</strong> en <strong>notes</strong> worden nu als hetzelfde herkend',
            en: 'Column names are no longer case-sensitive — <strong>Notes</strong> and <strong>notes</strong> are now treated as the same',
            de: 'Spaltennamen sind nicht mehr von Groß-/Kleinschreibung abhängig — <strong>Notes</strong> und <strong>notes</strong> werden jetzt gleich behandelt',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3.1',
    date: { nl: '4 juni 2026', en: '4 June 2026', de: '4. Juni 2026' },
    title: { nl: 'Hotfix', en: 'Hotfix', de: 'Hotfix' },
    groups: [
      {
        kind: 'fix',
        items: [
          {
            nl: 'Crashfix bij opstarten op <strong>macOS 26</strong>',
            en: 'Crash fix on startup on <strong>macOS 26</strong>',
            de: 'Absturz-Fix beim Start unter <strong>macOS 26</strong>',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.3',
    date: { nl: '29 mei 2026', en: '29 May 2026', de: '29. Mai 2026' },
    title: {
      nl: 'FAQ, layout mapper & macOS 26',
      en: 'FAQ, layout mapper & macOS 26',
      de: 'FAQ, Layout-Mapper & macOS 26',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>FAQ in de app</strong> — Help → FAQ opent een venster met veelgestelde vragen',
            en: '<strong>FAQ in the app</strong> — Help → FAQ opens a window with frequently asked questions',
            de: '<strong>FAQ in der App</strong> — Hilfe → FAQ öffnet ein Fenster mit häufig gestellten Fragen',
          },
          {
            nl: '<strong>Layout mapper</strong> — onbekend PDF-formaat? Wijs zelf kolommen toe en sla de indeling lokaal op',
            en: '<strong>Layout mapper</strong> — unknown PDF format? Assign columns yourself and save the layout locally',
            de: '<strong>Layout-Mapper</strong> — unbekanntes PDF-Format? Spalten selbst zuweisen und das Layout lokal speichern',
          },
          {
            nl: '<strong>Uitleg Apple-beveiliging</strong> — stap-voor-stap screenshots in de FAQ voor de macOS-beveiligingswaarschuwing',
            en: '<strong>Apple security explanation</strong> — step-by-step screenshots in the FAQ for the macOS security warning',
            de: '<strong>Erklärung zur Apple-Sicherheit</strong> — Schritt-für-Schritt-Screenshots in der FAQ zur macOS-Sicherheitswarnung',
          },
        ],
      },
      {
        kind: 'fix',
        items: [
          {
            nl: 'Crash op <strong>macOS 26</strong> opgelost (NSAssertionHandler + NSString retain-fix)',
            en: 'Crash on <strong>macOS 26</strong> fixed (NSAssertionHandler + NSString retain fix)',
            de: 'Absturz unter <strong>macOS 26</strong> behoben (NSAssertionHandler + NSString-Retain-Fix)',
          },
          {
            nl: 'Drag & Drop werkt nu correct in de gebouwde app (pyobjc gebundeld)',
            en: 'Drag & Drop now works correctly in the built app (pyobjc bundled)',
            de: 'Drag & Drop funktioniert jetzt korrekt in der gebauten App (pyobjc gebündelt)',
          },
          {
            nl: 'Interne formaataanduiding verwijderd uit zichtbaar gebruikerslog',
            en: 'Internal format identifier removed from the visible user log',
            de: 'Interne Formatkennung aus dem sichtbaren Benutzerprotokoll entfernt',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.2.1',
    date: { nl: '27 mei 2026', en: '27 May 2026', de: '27. Mai 2026' },
    title: {
      nl: 'In-app updater & activatiecheck',
      en: 'In-app updater & activation check',
      de: 'In-App-Updater & Aktivierungsprüfung',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>In-app updater</strong> — update direct vanuit de app, inclusief voortgangsbalk en automatisch herstarten',
            en: '<strong>In-app updater</strong> — update directly from the app, including progress bar and automatic restart',
            de: '<strong>In-App-Updater</strong> — direkt aus der App aktualisieren, inklusive Fortschrittsbalken und automatischem Neustart',
          },
          {
            nl: '<strong>Server-side activatiecheck</strong> — een serial kan niet meer op meerdere machines tegelijk worden gebruikt',
            en: '<strong>Server-side activation check</strong> — a serial can no longer be used on multiple machines at once',
            de: '<strong>Serverseitige Aktivierungsprüfung</strong> — eine Seriennummer kann nicht mehr gleichzeitig auf mehreren Rechnern verwendet werden',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.2',
    date: { nl: '27 mei 2026', en: '27 May 2026', de: '27. Mai 2026' },
    title: {
      nl: 'Automatische licentielevering',
      en: 'Automatic license delivery',
      de: 'Automatische Lizenzlieferung',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Automatische licentielevering via Mollie</strong> — serial direct per e-mail na betaling',
            en: '<strong>Automatic license delivery via Mollie</strong> — serial sent by email immediately after payment',
            de: '<strong>Automatische Lizenzlieferung über Mollie</strong> — Seriennummer direkt per E-Mail nach der Zahlung',
          },
        ],
      },
      {
        kind: 'fix',
        items: [
          {
            nl: 'Kolom-dropdown sluit nu correct wanneer je een bestand sleept',
            en: 'Column dropdown now closes correctly when you drag a file',
            de: 'Spalten-Dropdown schließt jetzt korrekt, wenn du eine Datei ziehst',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.1',
    date: { nl: '26 mei 2026', en: '26 May 2026', de: '26. Mai 2026' },
    title: {
      nl: 'Multi-bestand & verbeterde stabiliteit',
      en: 'Multi-file & improved stability',
      de: 'Mehrere Dateien & verbesserte Stabilität',
    },
    groups: [
      {
        kind: 'new',
        items: [
          {
            nl: '<strong>Meerdere bestanden tegelijk</strong> uploaden via drag & drop',
            en: 'Upload <strong>multiple files at once</strong> via drag & drop',
            de: '<strong>Mehrere Dateien gleichzeitig</strong> per Drag & Drop hochladen',
          },
          {
            nl: 'Algemeen commentaar per slate nu ook invoerbaar',
            en: 'General comment per slate can now also be entered',
            de: 'Allgemeiner Kommentar pro Slate jetzt ebenfalls eingebbar',
          },
        ],
      },
      {
        kind: 'improve',
        items: [
          {
            nl: 'Drag & drop verbeterd en stabieler',
            en: 'Drag & drop improved and more stable',
            de: 'Drag & Drop verbessert und stabiler',
          },
          {
            nl: 'Update-check robuuster (timeout 10s, betere foutafhandeling)',
            en: 'Update check more robust (10s timeout, better error handling)',
            de: 'Update-Prüfung robuster (10s Timeout, bessere Fehlerbehandlung)',
          },
        ],
      },
      {
        kind: 'fix',
        items: [
          {
            nl: 'Laatste take ontving geen algemene opmerking (page_note) — opgelost',
            en: 'Last take did not receive the general note (page_note) — fixed',
            de: 'Letzter Take erhielt keinen allgemeinen Hinweis (page_note) — behoben',
          },
          {
            nl: 'Sound Notes en Camera Notes naar dezelfde kolom worden nu samengevoegd met <strong>/</strong> i.p.v. overschreven',
            en: 'Sound Notes and Camera Notes going to the same column are now merged with <strong>/</strong> instead of overwritten',
            de: 'Sound Notes und Camera Notes in derselben Spalte werden jetzt mit <strong>/</strong> zusammengeführt statt überschrieben',
          },
          {
            nl: 'Tijdcode-noten in rapport verstoren de rating niet meer',
            en: 'Timecode notes in the report no longer interfere with the rating',
            de: 'Timecode-Notizen im Bericht stören die Bewertung nicht mehr',
          },
          {
            nl: 'Foutmelding bij geen internet is vriendelijker en verstoort opstarten niet meer',
            en: 'The no-internet error message is friendlier and no longer interferes with startup',
            de: 'Die Fehlermeldung ohne Internet ist freundlicher und stört den Start nicht mehr',
          },
        ],
      },
    ],
  },

  {
    version: 'v1.0',
    date: { nl: '25 mei 2026', en: '25 May 2026', de: '25. Mai 2026' },
    title: { nl: 'Eerste release', en: 'First release', de: 'Erste Veröffentlichung' },
    note: {
      nl: 'De eerste publieke versie van Continuity Bridge.',
      en: 'The first public version of Continuity Bridge.',
      de: 'Die erste öffentliche Version von Continuity Bridge.',
    },
    groups: [],
  },
];
