const TRANSLATIONS = {
  nl: {
    nav_price:            '🎉 Introductieprijs: <s style="opacity:.45;text-decoration-color:var(--muted)">€ 14,99</s> € 4,99 / jaar',
    nav_feedback:         'Support',
    nav_feedback_label:   'Meld een bug of verzoek',
    nav_download:         'Download',

    hero_tag:             'v1.3.4 Beta',
    hero_h1:              'Van continuïteits&shy;rapport naar je <em>Avid Bin.</em>',
    hero_sub:             'Lees je PDF-continuïteitsrapporten uit en schrijf alle notities en ratings direct naar je Avid bin.',
    hero_cta_silicon:     '⬇ Download Apple Silicon',
    hero_cta_intel:       '⬇ Intel Mac',
    hero_cta_windows:     '🪟 Windows (10/11)',
    hero_date:            '4 juni 2026',
    hero_whats_new:       'Wat is er nieuw? →',
    hero_stat_silicon:    'macOS 14+ Silicon',
    hero_stat_intel:      'Intel · macOS 13+',
    hero_stat_price_sub:  'Intro · <s style="opacity:.5">€ 14,99</s>',

    steps_eyebrow:  'Werkwijze',
    steps_title:    'Drie stappen, klaar.',
    step1_title:    'Exporteer je bin als ALE-bestand',
    step1_body:     'Exporteer de bin met al het materiaal van je draaidag vanuit Avid Media Composer als ALE-bestand.',
    step2_title:    'Verwerk in Continuity Bridge',
    step2_body:     'Drag & Drop je ALE-bestand en je continuïteitsrapporten in Continuity Bridge, en klik op Verwerk. Dat is alles.',
    step3_title:    'Importeer terug in Avid',
    step3_body:     'Importeer je ALE-bestand terug in Avid. Alle comments en ratings uit je continuïteitsrapporten staan er nu gewoon in.',

    feat1_eyebrow:  'Rapporten',
    feat1_title:    'Lees je rapporten uit in seconden.',
    feat1_body:     'Continuity Bridge leest je continuïteitsrapporten uit en zet comments en ratings direct in je bin.',
    feat1_li1:      'Scènes, takes en beschrijvingen worden herkend',
    feat1_li2:      'Ratings ook in hun eigen kolom',
    feat1_li3:      'Gemaakt door een editor, voor editors',

    feat2_eyebrow:  'Avid ALE',
    feat2_title:    'Geen handmatig copy-pasten meer.',
    feat2_body:     'Het ALE-bestand dat Continuity Bridge aanmaakt merge je eenvoudig met je originele clips in Avid. Alle info wordt automatisch toegevoegd.',
    feat2_li1:      'Merge ALE metadata direct met je bestaande clips in Avid',
    feat2_li2:      'Je originele metadata blijft intact',
    feat2_li3:      'Opgeslagen naast je originele ALE',

    feat3_eyebrow:  'Resultaat',
    feat3_title:    'Zie direct wat de script supervisor had opgemerkt.',
    feat3_body:     'Comments, ratings en opmerkingen per take, gewoon zichtbaar in je bin. Precies waar je ze nodig hebt.',
    feat3_li1:      'Opmerkingen per take direct leesbaar',
    feat3_li2:      'Kies je eigen kolom waar welke note moet komen',
    feat3_li3:      'Geen extra vensters, geen zoeken',

    testimonial_quote:  '"Continuity Bridge bespaart me per draaidag minstens 20 minuten copy pasten."',
    testimonial_author: 'Max, Assistant Editor',

    faq_eyebrow: 'Veelgestelde vragen',
    faq_title:   'FAQ',

    faq1_q: 'Ik krijg een waarschuwing dat de app van een onbekende ontwikkelaar is — wat nu?',
    faq1_a: 'Dit is een standaard macOS-beveiliging voor apps buiten de App Store. Je kunt dit veilig negeren — Continuity Bridge bevat geen malware. Krijg je de melding dat de app niet geopend kan worden? <strong>Klik NIET op "Verplaats naar prullenmand".</strong> Doorloop in plaats daarvan deze stappen:',
    faq1_s1: '<strong style="color:var(--accent2)">Stap 1</strong> — Klik in de melding op <strong>Gereed</strong> (Done).',
    faq1_s2: '<strong style="color:var(--accent2)">Stap 2</strong> — Open <strong>Systeeminstellingen → Privacy en beveiliging</strong> en scroll naar beneden.',
    faq1_s3: '<strong style="color:var(--accent2)">Stap 3</strong> — Bij <strong>"Continuity Bridge" is geblokkeerd…</strong> klik je op <strong>Toch openen</strong>.',
    faq1_s4: '<strong style="color:var(--accent2)">Stap 4</strong> — Bevestig eenmalig met <strong>Touch ID</strong> of je wachtwoord.',
    faq1_note: 'Dit hoeft maar één keer. Updates via de in-app updater hebben hier geen last van.',

    faq2_q: 'Hoe importeer ik het verwerkte ALE terug in Avid?',
    faq2_a: 'Ga in Avid naar <strong>Preferences → User → Import → Shot Log</strong>. Kies onder Events de optie <strong>Merge events with known master clips</strong>. Zo voegt Avid de comments en ratings toe aan je bestaande clips in plaats van nieuwe clips aan te maken.',

    faq3_q: 'Welke PDF-formaten worden ondersteund?',
    faq3_a: 'Continuity Bridge ondersteunt de meeste gangbare continuïteitsrapporten. Werkt jouw rapport niet goed? Stuur het op via <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a> en we kijken ernaar.',

    faq4_q: 'Verdwijnt mijn info na het maken van een multiclip?',
    faq4_a: 'Dat kan. Importeer de ALE altijd <strong>vóórdat</strong> je multiclips aanmaakt. Avid draagt metadata niet automatisch over aan bestaande multiclips.',

    faq5_q: 'Werkt Continuity Bridge offline?',
    faq5_a: 'Ja, volledig. Na activatie heeft de app geen internetverbinding nodig. Verwerking gebeurt lokaal op je Mac of pc.',

    faq6_q: 'Kan ik de licentie op meerdere Macs gebruiken?',
    faq6_a: 'Een licentie is gekoppeld aan één machine. Ga je over naar een nieuwe Mac? Verwijder de licentie eerst op je oude Mac via <strong>Help → Verwijder licentie</strong>, en activeer daarna op je nieuwe Mac. Ben je dat vergeten? Stuur een mail naar <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a>.',

    faq7_q: 'Wat gebeurt er als mijn licentie verloopt?',
    faq7_a: 'Na een jaar stopt de app met verwerken totdat je verlengt. Je bestanden blijven gewoon intact — er verdwijnt niets.',

    faq8_q: 'Welke versie van Avid Media Composer heb ik nodig?',
    faq8_a: 'Elke versie die ALE-bestanden kan exporteren en importeren. Dat geldt voor alle gangbare versies van Avid Media Composer.',

    faq9_q: 'Mijn clips worden niet herkend — wat nu?',
    faq9_a: 'Controleer of de clipnamen in je ALE overeenkomen met de namen in het continuïteitsrapport. Kleine afwijkingen in naamgeving kunnen zorgen voor een mismatch. Neem contact op via <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a>.',

    pricing_tag:   '🎉 Speciale introductieprijs',
    pricing_name:  'Jaarlicentie',
    pricing_desc:  'Voor één Mac of pc, een jaar lang. Na betaling krijg je meteen de serial in je mail.',
    price_note:    'Betaling via Mollie · Serial direct per e-mail',
    btn_buy:       '🛒 Koop licentie',
    btn_checkout:  'Afrekenen via Mollie →',
    btn_loading:   'Bezig…',
    form_name:     'Naam',
    form_name_ph:  'Je volledige naam',
    form_email:    'E-mailadres',
    form_email_ph: 'voor@je-serial.nl',
    err_unknown:   'Er ging iets mis. Probeer het opnieuw.',

    feat_yes1: 'Eénjarige licentie, jouw Mac',
    feat_yes2: 'Gratis updates inbegrepen',
    feat_yes3: 'Werkt volledig offline',
    feat_yes4: 'macOS 13+ (Intel) · 14+ (Silicon)',
    feat_yes5: 'Windows 10 / 11',
    feat_yes6: 'Support via e-mail',
    feat_no1:  'Geen automatische verlenging',
    feat_no2:  'Geen account of cloud vereist',

    beta_text: 'Continuity Bridge is momenteel in beta en wordt actief doorontwikkeld. Hoewel de app uitgebreid getest wordt, kunnen sommige functies nog veranderen of onverwachte resultaten geven. Feedback, ideeën, vragen of bug reports zijn altijd welkom. Neem gerust contact op.',

    contact_eyebrow: 'Contact',
    contact_title:   'Een vraag of opmerking?',
    contact_sub:     'Voor algemene vragen kun je hier een bericht sturen. Heb je een bug gevonden of een verzoek? Gebruik dan het formulier hieronder.',
    contact_name:    'Naam',
    contact_name_ph: 'Je naam',
    contact_email:   'E-mailadres',
    contact_email_ph:'je@email.nl',
    contact_msg:     'Bericht',
    contact_msg_ph:  'Je vraag of opmerking…',
    contact_send:    'Verstuur bericht',
    contact_bug_sub: 'Iets gevonden dat niet werkt, of een idee voor een nieuwe functie?',
    contact_bug_btn: '🐛 Meld een bug of verzoek',

    dl_silicon_alt: 'Oudere Intel Mac? <a href="download.html?platform=intel" style="color:var(--accent);text-decoration:underline;">Download Intel versie</a>',
    dl_intel_alt:   'Apple Silicon Mac? <a href="download.html?platform=silicon" style="color:var(--accent);text-decoration:underline;">Download Silicon versie</a>',

    cl_page_tag:     'Versiegeschiedenis',
    cl_title:        'Wat is er nieuw?',
    cl_subtitle:     'Alle updates van Continuity Bridge, van nieuw naar oud.',
    cl_new:          'Nieuw',
    cl_improve:      'Verbeteringen',
    cl_fix:          'Bugfixes',
    cl_badge_latest: 'Nieuwste',
    cl_badge_beta:   'Beta',

    footer: '© 2026 Studio Michiel Boesveldt · Continuity Bridge',
  },

  en: {
    nav_price:            '🎉 Intro price: <s style="opacity:.45;text-decoration-color:var(--muted)">€ 14.99</s> € 4.99 / year',
    nav_feedback:         'Support',
    nav_feedback_label:   'Report a bug or request',
    nav_download:         'Download',

    hero_tag:             'v1.3.4 Beta',
    hero_h1:              'From continuity&shy;report to your <em>Avid Bin.</em>',
    hero_sub:             'Read your PDF continuity reports and write all notes and ratings directly to your Avid bin.',
    hero_cta_silicon:     '⬇ Download Apple Silicon',
    hero_cta_intel:       '⬇ Intel Mac',
    hero_cta_windows:     '🪟 Windows (10/11)',
    hero_date:            'June 4, 2026',
    hero_whats_new:       "What's new? →",
    hero_stat_silicon:    'macOS 14+ Silicon',
    hero_stat_intel:      'Intel · macOS 13+',
    hero_stat_price_sub:  'Intro · <s style="opacity:.5">€ 14.99</s>',

    steps_eyebrow:  'How it works',
    steps_title:    'Three steps, done.',
    step1_title:    'Export your bin as an ALE file',
    step1_body:     'Export the bin with all footage from your shooting day from Avid Media Composer as an ALE file.',
    step2_title:    'Process in Continuity Bridge',
    step2_body:     'Drag & Drop your ALE file and continuity reports into Continuity Bridge, then click Process. That\'s it.',
    step3_title:    'Import back into Avid',
    step3_body:     'Import your ALE file back into Avid. All comments and ratings from your continuity reports are now right there.',

    feat1_eyebrow:  'Reports',
    feat1_title:    'Read your reports in seconds.',
    feat1_body:     'Continuity Bridge reads your continuity reports and puts comments and ratings directly into your bin.',
    feat1_li1:      'Scenes, takes and descriptions are recognised',
    feat1_li2:      'Ratings in their own column too',
    feat1_li3:      'Made by an editor, for editors',

    feat2_eyebrow:  'Avid ALE',
    feat2_title:    'No more manual copy-pasting.',
    feat2_body:     'The ALE file Continuity Bridge creates can be easily merged with your original clips in Avid. All info is added automatically.',
    feat2_li1:      'Merge ALE metadata directly with your existing clips in Avid',
    feat2_li2:      'Your original metadata remains intact',
    feat2_li3:      'Saved next to your original ALE',

    feat3_eyebrow:  'Result',
    feat3_title:    'See instantly what the script supervisor noted.',
    feat3_body:     'Comments, ratings and notes per take, right there in your bin. Exactly where you need them.',
    feat3_li1:      'Per-take notes readable at a glance',
    feat3_li2:      'Choose your own column for each note',
    feat3_li3:      'No extra windows, no searching',

    testimonial_quote:  '"Continuity Bridge saves me at least 20 minutes of copy-pasting every shooting day."',
    testimonial_author: 'Max, Assistant Editor',

    faq_eyebrow: 'Frequently asked questions',
    faq_title:   'FAQ',

    faq1_q: 'I get a warning that the app is from an unknown developer — what now?',
    faq1_a: 'This is standard macOS security for apps outside the App Store. You can safely ignore this — Continuity Bridge contains no malware. Getting a message that the app can\'t be opened? <strong>Do NOT click "Move to Trash".</strong> Follow these steps instead:',
    faq1_s1: '<strong style="color:var(--accent2)">Step 1</strong> — In the dialog, click <strong>Done</strong>.',
    faq1_s2: '<strong style="color:var(--accent2)">Step 2</strong> — Open <strong>System Settings → Privacy & Security</strong> and scroll down.',
    faq1_s3: '<strong style="color:var(--accent2)">Step 3</strong> — Next to <strong>"Continuity Bridge" was blocked…</strong> click <strong>Open Anyway</strong>.',
    faq1_s4: '<strong style="color:var(--accent2)">Step 4</strong> — Confirm once with <strong>Touch ID</strong> or your password.',
    faq1_note: 'You only need to do this once. Updates via the in-app updater are unaffected.',

    faq2_q: 'How do I import the processed ALE back into Avid?',
    faq2_a: 'In Avid, go to <strong>Preferences → User → Import → Shot Log</strong>. Under Events, choose <strong>Merge events with known master clips</strong>. This way Avid adds the comments and ratings to your existing clips instead of creating new ones.',

    faq3_q: 'Which PDF formats are supported?',
    faq3_a: 'Continuity Bridge supports most common continuity reports. Does your report not work well? Send it to <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a> and we\'ll take a look.',

    faq4_q: 'Will my info disappear after creating a multiclip?',
    faq4_a: 'It can. Always import the ALE <strong>before</strong> creating multiclips. Avid does not automatically transfer metadata to existing multiclips.',

    faq5_q: 'Does Continuity Bridge work offline?',
    faq5_a: 'Yes, fully. After activation the app needs no internet connection. Processing happens locally on your Mac or PC.',

    faq6_q: 'Can I use the licence on multiple Macs?',
    faq6_a: 'A licence is tied to one machine. Moving to a new Mac? Remove the licence first on your old Mac via <strong>Help → Remove licence</strong>, then activate on your new Mac. Forgotten? Send an email to <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a>.',

    faq7_q: 'What happens when my licence expires?',
    faq7_a: 'After one year the app stops processing until you renew. Your files remain completely intact — nothing is deleted.',

    faq8_q: 'Which version of Avid Media Composer do I need?',
    faq8_a: 'Any version that can export and import ALE files. That applies to all common versions of Avid Media Composer.',

    faq9_q: 'My clips are not recognised — what now?',
    faq9_a: 'Check that the clip names in your ALE match the names in the continuity report. Small naming differences can cause a mismatch. Contact us at <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a>.',

    pricing_tag:   '🎉 Special intro price',
    pricing_name:  'Annual licence',
    pricing_desc:  'For one Mac or PC, for one year. After payment you immediately receive your serial by email.',
    price_note:    'Payment via Mollie · Serial delivered by email',
    btn_buy:       '🛒 Buy licence',
    btn_checkout:  'Checkout via Mollie →',
    btn_loading:   'Processing…',
    form_name:     'Name',
    form_name_ph:  'Your full name',
    form_email:    'Email address',
    form_email_ph: 'your@email.com',
    err_unknown:   'Something went wrong. Please try again.',

    feat_yes1: 'One-year licence, your Mac',
    feat_yes2: 'Free updates included',
    feat_yes3: 'Works fully offline',
    feat_yes4: 'macOS 13+ (Intel) · 14+ (Silicon)',
    feat_yes5: 'Windows 10 / 11',
    feat_yes6: 'Support via email',
    feat_no1:  'No automatic renewal',
    feat_no2:  'No account or cloud required',

    beta_text: 'Continuity Bridge is currently in beta and is actively being developed. Although the app is extensively tested, some features may still change or produce unexpected results. Feedback, ideas, questions or bug reports are always welcome.',

    contact_eyebrow: 'Contact',
    contact_title:   'A question or comment?',
    contact_sub:     'For general questions you can send a message here. Found a bug or have a feature request? Use the form below.',
    contact_name:    'Name',
    contact_name_ph: 'Your name',
    contact_email:   'Email address',
    contact_email_ph:'your@email.com',
    contact_msg:     'Message',
    contact_msg_ph:  'Your question or comment…',
    contact_send:    'Send message',
    contact_bug_sub: 'Found something that doesn\'t work, or have an idea for a new feature?',
    contact_bug_btn: '🐛 Report a bug or request',

    dl_silicon_alt: 'Older Intel Mac? <a href="download.html?platform=intel" style="color:var(--accent);text-decoration:underline;">Download Intel version</a>',
    dl_intel_alt:   'Apple Silicon Mac? <a href="download.html?platform=silicon" style="color:var(--accent);text-decoration:underline;">Download Silicon version</a>',

    cl_page_tag:     'Version history',
    cl_title:        'What\'s new?',
    cl_subtitle:     'All Continuity Bridge updates, newest first.',
    cl_new:          'New',
    cl_improve:      'Improvements',
    cl_fix:          'Bug fixes',
    cl_badge_latest: 'Latest',
    cl_badge_beta:   'Beta',

    footer: '© 2026 Studio Michiel Boesveldt · Continuity Bridge',
  },

  de: {
    nav_price:            '🎉 Einführungspreis: <s style="opacity:.45;text-decoration-color:var(--muted)">€ 14,99</s> € 4,99 / Jahr',
    nav_feedback:         'Support',
    nav_feedback_label:   'Bug oder Anfrage melden',
    nav_download:         'Download',

    hero_tag:             'v1.3.4 Beta',
    hero_h1:              'Vom Kontinuitäts&shy;bericht in dein <em>Avid Bin.</em>',
    hero_sub:             'Lese deine PDF-Kontinuitätsberichte aus und schreibe alle Notizen und Bewertungen direkt in dein Avid-Bin.',
    hero_cta_silicon:     '⬇ Download Apple Silicon',
    hero_cta_intel:       '⬇ Intel Mac',
    hero_cta_windows:     '🪟 Windows (10/11)',
    hero_date:            '4. Juni 2026',
    hero_whats_new:       'Was ist neu? →',
    hero_stat_silicon:    'macOS 14+ Silicon',
    hero_stat_intel:      'Intel · macOS 13+',
    hero_stat_price_sub:  'Intro · <s style="opacity:.5">€ 14,99</s>',

    steps_eyebrow:  'So funktioniert es',
    steps_title:    'Drei Schritte, fertig.',
    step1_title:    'Exportiere dein Bin als ALE-Datei',
    step1_body:     'Exportiere das Bin mit dem gesamten Material deines Drehtages aus Avid Media Composer als ALE-Datei.',
    step2_title:    'Verarbeite in Continuity Bridge',
    step2_body:     'Ziehe deine ALE-Datei und deine Kontinuitätsberichte per Drag & Drop in Continuity Bridge und klicke auf Verarbeiten. Das ist alles.',
    step3_title:    'Importiere zurück in Avid',
    step3_body:     'Importiere deine ALE-Datei zurück in Avid. Alle Kommentare und Bewertungen aus deinen Kontinuitätsberichten sind jetzt direkt vorhanden.',

    feat1_eyebrow:  'Berichte',
    feat1_title:    'Lese deine Berichte in Sekunden aus.',
    feat1_body:     'Continuity Bridge liest deine Kontinuitätsberichte aus und schreibt Kommentare und Bewertungen direkt in dein Bin.',
    feat1_li1:      'Szenen, Takes und Beschreibungen werden erkannt',
    feat1_li2:      'Bewertungen auch in ihrer eigenen Spalte',
    feat1_li3:      'Von einem Editor, für Editoren',

    feat2_eyebrow:  'Avid ALE',
    feat2_title:    'Kein manuelles Kopieren mehr.',
    feat2_body:     'Die von Continuity Bridge erstellte ALE-Datei lässt sich einfach mit deinen Original-Clips in Avid zusammenführen. Alle Informationen werden automatisch hinzugefügt.',
    feat2_li1:      'ALE-Metadaten direkt mit bestehenden Clips in Avid zusammenführen',
    feat2_li2:      'Deine Originalmetadaten bleiben erhalten',
    feat2_li3:      'Neben deiner Original-ALE gespeichert',

    feat3_eyebrow:  'Ergebnis',
    feat3_title:    'Sieh sofort, was die Continuity-Supervisorin notiert hat.',
    feat3_body:     'Kommentare, Bewertungen und Notizen pro Take, direkt in deinem Bin sichtbar. Genau dort, wo du sie brauchst.',
    feat3_li1:      'Notizen pro Take auf einen Blick lesbar',
    feat3_li2:      'Wähle deine eigene Spalte für jede Notiz',
    feat3_li3:      'Keine extra Fenster, kein Suchen',

    testimonial_quote:  '"Continuity Bridge spart mir pro Drehtag mindestens 20 Minuten Kopierarbeit."',
    testimonial_author: 'Max, Assistant Editor',

    faq_eyebrow: 'Häufig gestellte Fragen',
    faq_title:   'FAQ',

    faq1_q: 'Ich erhalte eine Warnung, dass die App von einem unbekannten Entwickler stammt — was jetzt?',
    faq1_a: 'Das ist eine standardmäßige macOS-Sicherheitsfunktion für Apps außerhalb des App Stores. Du kannst dies sicher ignorieren — Continuity Bridge enthält keine Malware. Erscheint die Meldung, dass die App nicht geöffnet werden kann? <strong>Klicke NICHT auf "In den Papierkorb legen".</strong> Führe stattdessen diese Schritte aus:',
    faq1_s1: '<strong style="color:var(--accent2)">Schritt 1</strong> — Klicke im Dialog auf <strong>Fertig</strong>.',
    faq1_s2: '<strong style="color:var(--accent2)">Schritt 2</strong> — Öffne <strong>Systemeinstellungen → Datenschutz & Sicherheit</strong> und scrolle nach unten.',
    faq1_s3: '<strong style="color:var(--accent2)">Schritt 3</strong> — Bei <strong>„Continuity Bridge" wurde blockiert…</strong> klicke auf <strong>Trotzdem öffnen</strong>.',
    faq1_s4: '<strong style="color:var(--accent2)">Schritt 4</strong> — Bestätige einmalig mit <strong>Touch ID</strong> oder deinem Passwort.',
    faq1_note: 'Das ist nur einmal nötig. Updates über den In-App-Updater sind davon nicht betroffen.',

    faq2_q: 'Wie importiere ich die verarbeitete ALE zurück in Avid?',
    faq2_a: 'Gehe in Avid zu <strong>Preferences → User → Import → Shot Log</strong>. Wähle unter Events die Option <strong>Merge events with known master clips</strong>. So fügt Avid die Kommentare und Bewertungen zu deinen bestehenden Clips hinzu, anstatt neue zu erstellen.',

    faq3_q: 'Welche PDF-Formate werden unterstützt?',
    faq3_a: 'Continuity Bridge unterstützt die meisten gängigen Kontinuitätsberichte. Funktioniert dein Bericht nicht richtig? Schicke ihn an <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a> und wir schauen es uns an.',

    faq4_q: 'Gehen meine Informationen nach dem Erstellen eines Multiclips verloren?',
    faq4_a: 'Das kann passieren. Importiere die ALE immer <strong>bevor</strong> du Multiclips erstellst. Avid überträgt Metadaten nicht automatisch auf bestehende Multiclips.',

    faq5_q: 'Funktioniert Continuity Bridge offline?',
    faq5_a: 'Ja, vollständig. Nach der Aktivierung benötigt die App keine Internetverbindung. Die Verarbeitung erfolgt lokal auf deinem Mac oder PC.',

    faq6_q: 'Kann ich die Lizenz auf mehreren Macs verwenden?',
    faq6_a: 'Eine Lizenz ist an eine Maschine gebunden. Wechselst du zu einem neuen Mac? Entferne die Lizenz zuerst auf deinem alten Mac über <strong>Hilfe → Lizenz entfernen</strong> und aktiviere dann auf deinem neuen Mac. Vergessen? Schicke eine E-Mail an <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a>.',

    faq7_q: 'Was passiert, wenn meine Lizenz abläuft?',
    faq7_a: 'Nach einem Jahr stellt die App die Verarbeitung ein, bis du verlängerst. Deine Dateien bleiben vollständig erhalten — es wird nichts gelöscht.',

    faq8_q: 'Welche Version von Avid Media Composer benötige ich?',
    faq8_a: 'Jede Version, die ALE-Dateien exportieren und importieren kann. Das gilt für alle gängigen Versionen von Avid Media Composer.',

    faq9_q: 'Meine Clips werden nicht erkannt — was nun?',
    faq9_a: 'Überprüfe, ob die Clip-Namen in deiner ALE mit den Namen im Kontinuitätsbericht übereinstimmen. Kleine Abweichungen in der Benennung können zu einem Mismatch führen. Kontaktiere uns unter <a href="mailto:support@studiomichielboesveldt.nl">support@studiomichielboesveldt.nl</a>.',

    pricing_tag:   '🎉 Spezieller Einführungspreis',
    pricing_name:  'Jahreslizenz',
    pricing_desc:  'Für einen Mac oder PC, für ein Jahr. Nach der Zahlung erhältst du sofort die Seriennummer per E-Mail.',
    price_note:    'Zahlung über Mollie · Seriennummer sofort per E-Mail',
    btn_buy:       '🛒 Lizenz kaufen',
    btn_checkout:  'Zur Kasse via Mollie →',
    btn_loading:   'Wird verarbeitet…',
    form_name:     'Name',
    form_name_ph:  'Dein vollständiger Name',
    form_email:    'E-Mail-Adresse',
    form_email_ph: 'deine@email.de',
    err_unknown:   'Etwas ist schiefgelaufen. Bitte versuche es erneut.',

    feat_yes1: 'Einjährige Lizenz, dein Mac',
    feat_yes2: 'Kostenlose Updates inklusive',
    feat_yes3: 'Funktioniert vollständig offline',
    feat_yes4: 'macOS 13+ (Intel) · 14+ (Silicon)',
    feat_yes5: 'Windows 10 / 11',
    feat_yes6: 'Support per E-Mail',
    feat_no1:  'Keine automatische Verlängerung',
    feat_no2:  'Kein Konto oder Cloud erforderlich',

    beta_text: 'Continuity Bridge befindet sich derzeit in der Beta-Phase und wird aktiv weiterentwickelt. Obwohl die App ausgiebig getestet wird, können sich einige Funktionen noch ändern oder unerwartete Ergebnisse liefern. Feedback, Ideen, Fragen oder Fehlerberichte sind jederzeit willkommen.',

    contact_eyebrow: 'Kontakt',
    contact_title:   'Eine Frage oder Anmerkung?',
    contact_sub:     'Für allgemeine Fragen kannst du hier eine Nachricht senden. Hast du einen Bug gefunden oder eine Anfrage? Nutze das Formular unten.',
    contact_name:    'Name',
    contact_name_ph: 'Dein Name',
    contact_email:   'E-Mail-Adresse',
    contact_email_ph:'deine@email.de',
    contact_msg:     'Nachricht',
    contact_msg_ph:  'Deine Frage oder Anmerkung…',
    contact_send:    'Nachricht senden',
    contact_bug_sub: 'Etwas gefunden, das nicht funktioniert, oder eine Idee für eine neue Funktion?',
    contact_bug_btn: '🐛 Bug oder Anfrage melden',

    dl_silicon_alt: 'Älterer Intel Mac? <a href="download.html?platform=intel" style="color:var(--accent);text-decoration:underline;">Intel-Version herunterladen</a>',
    dl_intel_alt:   'Apple Silicon Mac? <a href="download.html?platform=silicon" style="color:var(--accent);text-decoration:underline;">Silicon-Version herunterladen</a>',

    cl_page_tag:     'Versionsverlauf',
    cl_title:        'Was ist neu?',
    cl_subtitle:     'Alle Updates von Continuity Bridge, neueste zuerst.',
    cl_new:          'Neu',
    cl_improve:      'Verbesserungen',
    cl_fix:          'Fehlerbehebungen',
    cl_badge_latest: 'Neueste',
    cl_badge_beta:   'Beta',

    footer: '© 2026 Studio Michiel Boesveldt · Continuity Bridge',
  },
};

// ── i18n engine ──────────────────────────────────────────────────────────────
function getLang() {
  const saved = localStorage.getItem('cb_lang');
  if (saved && TRANSLATIONS[saved]) return saved;
  const browser = (navigator.language || 'nl').slice(0, 2).toLowerCase();
  return TRANSLATIONS[browser] ? browser : 'nl';
}

function applyLang(lang) {
  if (!TRANSLATIONS[lang]) lang = 'nl';
  localStorage.setItem('cb_lang', lang);
  const t = TRANSLATIONS[lang];

  // Simple text nodes
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (t[key] !== undefined) el.textContent = t[key];
  });

  // HTML content
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const key = el.dataset.i18nHtml;
    if (t[key] !== undefined) el.innerHTML = t[key];
  });

  // Placeholders
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const key = el.dataset.i18nPh;
    if (t[key] !== undefined) el.placeholder = t[key];
  });

  // Lang switcher active state
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === lang);
  });

  // html lang attribute
  document.documentElement.lang = lang;
}

document.addEventListener('DOMContentLoaded', () => {
  applyLang(getLang());
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.addEventListener('click', () => applyLang(btn.dataset.lang));
  });
});
