<h1 align="center">Powerness M01 · EPP BES – Home Assistant</h1>

<p align="center"><a href="README.md">English</a> · <b>Deutsch</b></p>

<p align="center">
  <img src="docs/images/device.svg" alt="Balkonkraftwerk-Speicher M01" width="420">
</p>

<p align="center">
  Lokale Integration für den Balkonkraftwerk-Speicher <b>Powerness M01</b> bzw. <b>EPP BES 1,5 kWh</b> (Hersteller: DMEGC).<br>
  Einrichtung per QR-Code, danach alles lokal im WLAN – ohne Zusatz-Integrationen, Helfer oder Automationen.
</p>

<p align="center">
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square" alt="HACS Custom"></a>
  <a href="https://github.com/kuuuraaa/ha-powerness-m01/releases"><img src="https://img.shields.io/github/v/release/kuuuraaa/ha-powerness-m01?style=flat-square" alt="Release"></a>
  <img src="https://img.shields.io/badge/Home%20Assistant-2025.2%2B-18BCF2?style=flat-square" alt="Home Assistant 2025.2+">
  <img src="https://img.shields.io/badge/IoT-local__push-2da44e?style=flat-square" alt="local push">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/kuuuraaa/ha-powerness-m01?style=flat-square" alt="Lizenz"></a>
</p>

---

## Warum diese Integration?

Der M01 (bzw. der baugleiche EPP BES) ist ein Tuya-Gerät, das aber fast alle Messwerte als
**verschlüsselte Binärblöcke** meldet. Die offizielle Tuya-Integration zeigt deshalb nichts an.
Bisher brauchte man ein Bündel aus *Xtend Tuya*, *LocalTuya*, einem halben Dutzend
Template-Sensoren, Integral-Helfern und einer Automation, die den Speicher jede Minute „aufweckt“ –
weil er Live-Daten sonst nur sendet, solange die App offen ist.

Diese Integration ersetzt das alles:

- 🔌 **Einrichtung in zwei Minuten** – Benutzercode aus der Smart-Life-App eingeben, QR-Code
  scannen, fertig. Kein Tuya-Developer-Account, kein Local Key abschreiben.
- 🏠 **Komplett lokal** – die Cloud wird nur einmal gebraucht, um den Local Key abzuholen.
  Danach spricht Home Assistant direkt und verschlüsselt (Tuya-Protokoll 3.4) mit dem Speicher.
- ⚡ **Live-Daten per Push** – etwa alle 5 Sekunden, ohne Polling. Die Integration hält den
  Speicher selbst wach, die alte Wake-Automation entfällt.
- 📊 **Fertig fürs Energie-Dashboard** – Energiezähler für Laden, Entladen und PV sind eingebaut.
- 🗓️ **Zeitplan steuern** – bis zu vier Lade-/Entladezeiträume wie in der App, direkt aus HA
  oder per Automation.
- 🔁 **Robust** – findet den Speicher nach einem IP-Wechsel selbst wieder und merkt sich
  den Zeitplan über Neustarts.

## So funktioniert es

1. **Einrichtung:** Über denselben QR-Login, den auch die offizielle Tuya-Integration nutzt,
   holt die Integration Geräte-ID und Local Key aus deinem Smart-Life-Konto.
2. **Verbindung:** Der Speicher wird über seine UDP-Broadcasts im WLAN gefunden. Home Assistant
   baut eine dauerhafte, verschlüsselte Verbindung auf (Session-Key-Handshake nach Tuya 3.4).
3. **Daten:** Die Binärwerte werden direkt in der Integration entschlüsselt und als normale
   Sensoren bereitgestellt. Wenn die Live-Daten älter als 30 Sekunden sind, schickt die
   Integration denselben Befehl, den auch die App beim Öffnen sendet.

## Unterstützte Geräte

| Gerät | Status |
|---|---|
| **Powerness M01** | ✅ getestet (Firmware 3.0.9, Protokoll 3.4) |
| **EPP BES 1,5 kWh** | ✅ baugleich, gleiche Tuya-Produkt-ID |
| **DMEGC M01** | ✅ Originalgerät (die Seriennummern beginnen mit `DCM01`) |
| Andere Tuya-Speicher der Kategorie `cnsb` („Micro Battery“) | 🟡 werden angeboten, aber ungetestet |
| Mehrere Akkus im Verbund | 🟡 Gesamtwerte funktionieren, Einzelwerte pro Akku folgen |

Du hast einen anderen Speicher oder mehrere Akkus? Ein [Issue](https://github.com/kuuuraaa/ha-powerness-m01/issues)
mit dem Diagnose-Download hilft enorm (der Local Key wird darin automatisch ausgeblendet).

## Installation

### Über HACS (empfohlen)

[![Repository in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kuuuraaa&repository=ha-powerness-m01&category=integration)

Oder von Hand:

1. **HACS → ⋮ → Benutzerdefinierte Repositories**
2. URL `https://github.com/kuuuraaa/ha-powerness-m01` eintragen, Typ **Integration**
3. **Powerness M01 / EPP BES Battery** installieren
4. Home Assistant **neu starten**

### Manuell

Den Ordner `custom_components/powerness` aus dem
[neuesten Release](https://github.com/kuuuraaa/ha-powerness-m01/releases) nach
`/config/custom_components/` kopieren (z. B. mit dem Add-on *Samba share* oder
*Studio Code Server*) und Home Assistant neu starten.

## Einrichtung

[![Integration hinzufügen](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=powerness)

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Powerness“**
2. **„Mit der Smart-Life-/Tuya-App anmelden“** wählen
3. In der App: **Ich → Einstellungen → Konto und Sicherheit → Benutzercode** – den Code eingeben
4. Den angezeigten **QR-Code mit der App scannen**, in der App bestätigen, **Absenden** klicken
5. Fertig – der Speicher wird im Netzwerk gesucht und eingerichtet

> [!IMPORTANT]
> Tuya-Geräte erlauben **nur eine lokale Verbindung** gleichzeitig. Ist der Speicher in
> **LocalTuya** oder **Tuya Local** eingerichtet, dort bitte vorher entfernen oder deaktivieren.
> Die App, Xtend Tuya und die offizielle Tuya-Integration (alle über die Cloud) stören nicht.

<details>
<summary><b>Manuelle Einrichtung mit Local Key</b></summary>

Wer den Local Key schon hat (z. B. aus LocalTuya oder tinytuya), kann statt des QR-Logins
**„Geräte-ID und Local Key manuell eingeben“** wählen. Die IP-Adresse kann leer bleiben, dann
wird der Speicher automatisch gesucht. Protokollversion ist beim M01 **3.4**.
</details>

## Entitäten

### Messwerte

| Entität | Einheit | Beschreibung |
|---|---|---|
| **Ladezustand** | % | SOC aus den Live-Daten |
| **Spannung** | V | Batteriespannung |
| **Strom** | A | positiv = Laden, negativ = Entladen |
| **Ladeleistung** | W | Leistung in den Akku (immer ≥ 0) |
| **Entladeleistung** | W | Leistung aus dem Akku (immer ≥ 0) |
| **PV-Strom** | A | Strom vom Solarmodul |
| **PV-Leistung** | W | PV-Strom × Batteriespannung |
| **Temperatur** | °C | Temperatur im Speicher |
| **Batteriestatus** | – | *Laden*, *Entladen* oder *Standby* – wie in der App |
| **Zeitplan** | – | was laut Zeitplan gerade gilt: *Laden*, *Entladen*, *Aus* oder *Dauerhaft (Schalter)* |

### Energie (für das Energie-Dashboard)

| Entität | Beschreibung |
|---|---|
| **Geladene Energie** | kWh, in der Integration aus der Ladeleistung hochgerechnet |
| **Entladene Energie** | kWh, aus der Entladeleistung hochgerechnet |
| **PV-Energie** | kWh, aus der PV-Leistung hochgerechnet |
| **Geladene / Entladene Energie (Gerätezähler)** | Lebenszeit-Zähler des Speichers (0,1 kWh Auflösung) |
| **PV-Energie (Gerätezähler)** | PV-Gesamtertrag laut Speicher |

Im Energie-Dashboard bei **Batteriespeicher** „Geladene Energie“ als *Energie in die Batterie* und
„Entladene Energie“ als *Energie aus der Batterie* eintragen, bei **Solar** die „PV-Energie“.
Die Gerätezähler eignen sich ebenso; sie zählen auch weiter, während Home Assistant aus ist,
haben aber nur 0,1 kWh Auflösung.

### Steuerung

| Entität | Beschreibung |
|---|---|
| **Dauerhaft laden** / **Dauerhaft entladen** | die „dauerhafte Aktion“ der App |
| **Zeitraum 1–4 von / bis / Modus** | der Zeitplan der App (*Konfiguration* auf der Geräteseite) |
| **Live-Daten anfordern** | weckt den Speicher sofort auf (passiert sonst automatisch) |

### Diagnose

| Entität | Beschreibung |
|---|---|
| **Alarm** | an, sobald der Speicher einen Alarm meldet; die Codes stehen im Attribut `active_codes` |
| **Letzte Live-Daten** | Zeitpunkt der letzten Live-Meldung |

## Zeitplan

Der Speicher kennt – wie die App – zwei Betriebsarten:

| Betriebsart | So aktivierst du sie |
|---|---|
| **Dauerhaft** | *Dauerhaft laden* und/oder *Dauerhaft entladen* einschalten. Der Zeitplan wird dann ignoriert. |
| **Zeitplan** | Beide Dauerhaft-Schalter **aus**. Dann gelten die bis zu vier Zeiträume. |

Jeder der vier Zeiträume hat **von**, **bis** und einen **Modus** (*Aus*, *Laden*, *Entladen*).
Ein Zeitraum auf *Aus* behält seine Zeiten, wird aber nicht an den Speicher geschickt – so kann
man Zeiträume schnell an- und abschalten, ohne dass die anderen verrutschen. Wird der Zeitplan
in der App geändert, übernimmt Home Assistant ihn automatisch.

> [!TIP]
> Für „bis Mitternacht“ `23:59` verwenden – so macht es auch die App.
> Mindestens ein Zeitraum muss aktiv bleiben; zum Abschalten des Zeitplans die Dauerhaft-Schalter nutzen.

### Aktion `powerness.set_schedule`

Ersetzt den kompletten Zeitplan in einem Rutsch – ideal für Automationen:

```yaml
action: powerness.set_schedule
data:
  config_entry_id: <Speicher auswählen>
  periods:
    - {start: "10:00", end: "16:00", mode: charge}
    - {start: "18:00", end: "23:59", mode: discharge}
```

## Beispiele

<details>
<summary><b>Im Sommerhalbjahr tagsüber laden, abends einspeisen</b></summary>

```yaml
automation:
  - alias: "Speicher: Sommer-Zeitplan"
    triggers:
      - trigger: time
        at: "00:05:00"
    conditions:
      - condition: template
        value_template: "{{ now().month in [4, 5, 6, 7, 8, 9] }}"
    actions:
      - action: switch.turn_off
        target:
          entity_id:
            - switch.balkonkraftwerk_batterie_dauerhaft_laden
            - switch.balkonkraftwerk_batterie_dauerhaft_entladen
      - action: powerness.set_schedule
        data:
          config_entry_id: DEINE_ENTRY_ID  # im Automations-Editor einfach den Speicher auswählen
          periods:
            - {start: "08:00", end: "17:00", mode: charge}
            - {start: "17:00", end: "23:59", mode: discharge}
```

Die Entity-IDs hängen vom Namen deines Geräts ab – bitte anpassen.
</details>

<details>
<summary><b>Benachrichtigung, wenn der Speicher voll ist</b></summary>

```yaml
automation:
  - alias: "Speicher voll"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.balkonkraftwerk_batterie_ladezustand
        above: 99
    actions:
      - action: notify.notify
        data:
          message: "Der Balkonspeicher ist voll ☀️🔋"
```
</details>

## Optionen

Unter **Einstellungen → Geräte & Dienste → Powerness → Konfigurieren**:

- **Live-Daten automatisch anfordern** (Standard: an) – hält den Speicher wach, damit die
  Werte laufend aktualisiert werden. Abschalten, wenn nur die App Live-Daten auslösen soll.

## Umstieg von der Bastellösung

Wer bisher Xtend Tuya + LocalTuya + Template-Helfer genutzt hat:

1. In **LocalTuya** den Speicher entfernen (sonst blockiert er die lokale Verbindung).
2. Diese Integration einrichten.
3. Im **Energie-Dashboard** die neuen Energie-Sensoren eintragen.
4. Danach können gelöscht werden: die Wake-Automation (`localtuya.set_dp` mit `AQEBAQE=`),
   die Template-Sensoren für Leistung/Spannung/Strom/SOC und die Integral-Helfer.
   Xtend Tuya und LocalTuya werden für den Speicher nicht mehr gebraucht.

## Fehlerbehebung

<details>
<summary><b>„Keine Verbindung zum Speicher“ bei der Einrichtung</b></summary>

- Ist der Speicher noch in **LocalTuya / Tuya Local** eingerichtet? Dort entfernen.
- Sind Home Assistant und Speicher im **gleichen Netz**? Die automatische Suche nutzt
  UDP-Broadcasts (Port 6666/6667), die nicht über Router/VLANs hinweg gehen. Dann die
  IP-Adresse von Hand eingeben.
- Der Speicher braucht nach einem Neustart manchmal eine Minute, bis er lokal erreichbar ist.
</details>

<details>
<summary><b>„Der Speicher hat den Local Key abgelehnt“</b></summary>

Der Local Key ändert sich, wenn der Speicher in der App neu gekoppelt wird. Die Integration
fragt dann von selbst nach einer neuen Anmeldung per QR-Code.
</details>

<details>
<summary><b>Werte aktualisieren sich nur selten</b></summary>

Prüfe, ob die Option **Live-Daten automatisch anfordern** an ist, und schau auf den Sensor
**Letzte Live-Daten**. Mit dem Button **Live-Daten anfordern** kannst du es sofort testen.
</details>

<details>
<summary><b>Zeitplan zeigt nach dem Neustart nichts an</b></summary>

Der Speicher meldet seinen Zeitplan nur, wenn er sich ändert. Die Integration fragt ihn nach
dem Verbinden gezielt ab und merkt ihn sich – beim allerersten Start kann er trotzdem leer sein,
bis du einmal einen Zeitraum setzt oder ihn in der App änderst.
</details>

<details>
<summary><b>Debug-Log aktivieren</b></summary>

Auf der Integrationsseite **Debug-Protokollierung aktivieren**. Jede Meldung des Speichers
wird dann mit allen Rohwerten als Hex geloggt. Für Fehlerberichte ist der
**Diagnose-Download** (Geräteseite → ⋮) noch hilfreicher – der Local Key wird darin automatisch entfernt.
</details>

## Technische Details

<details>
<summary><b>Datenpunkte und Binärformate</b></summary>

Für alle, die weitere Werte entschlüsseln wollen. Der Diagnose-Download enthält alle
Roh-Datenpunkte zusätzlich als Hex.

| DP | Name | Format |
|---|---|---|
| 1 | `get_terminal_data` | Wake-Befehl `AQEBAQE=` (`01 01 01 01 01`) |
| 2 | `stack_info` | `01 01` + TLV: `0x0C` SOC, `0x0E`/`0x0F` Energie geladen/entladen ×0,1 kWh, `0x12` Spannung ×0,1 V, `0x13` Strom ×0,1 A (signed) |
| 4 | `bms_message` | `01 01` + Seriennummer + TLV: `0x03` SOC, `0x08` Spannung, `0x0A` Strom, `0x23`/`0x24` vermutlich Index der höchsten/niedrigsten Zelle, `0x25`/`0x26` Energie ×0,1 kWh |
| 8 | `bcu_info_hex` | `01 01` + Seriennummer + TLV: `0x07` Batteriestatus (`0` Laden, `1` Entladen, `2` Standby) |
| 9 | `alarm_message` | `01 01` + Seriennummer + TLV, je ein Byte pro Alarm |
| 10 | `battery_dc_data` | `01` + Blöcke à 29 Byte: Seriennummer (22) · SOC (1) · Spannung ×0,1 V (2) · Strom ×0,1 A signed (2) · ? signed (2). Block 1 = Gesamtsystem, danach je Akku |
| 101 / 102 | `charger_switch` / `discharge_switch` | Dauerhaft laden / entladen |
| 103 | `time_schedule` | bis zu 4 × 6 Byte: Start h, Start min, Ende h, Ende min, Laden, Entladen |
| 104 | `temperature` | °C (ganzzahlig) |
| 105 | `firmware` | Text |
| 107 | `pv_total` | PV-Gesamtertrag ×0,1 kWh |
| 108 | `pv_curr` | PV-Strom ×0,1 A |

TLV = Tag (1 Byte), Länge (1 Byte), Wert (big-endian). Die Skalierung der Energiezähler ist über
zwei Snapshots im Abstand von einigen Wochen bestätigt (PV +30,4 kWh, geladen +31,3 kWh,
entladen +28,7 kWh).

**Noch offen:** BMS-Tag `0x1C`, die Bedeutung der Alarm-Codes, die letzten 2 Byte der
Live-Datenblöcke (`0` Leerlauf, `+3` Laden, `−1` Entladen) und `status_pv` (DP 106).
Die WLAN-Signalstärke aus der App kommt aus der Tuya-Cloud und ist lokal nicht verfügbar.
</details>

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component tuya-device-sharing-sdk
pytest
```

Die Tests laufen gegen einen simulierten Speicher (`tests/fake_device.py`), der die
Geräteseite des Tuya-3.4-Protokolls spricht – inklusive Handshake, Verschlüsselung und
Push-Meldungen. Die Testdaten stammen von einem echten M01 (Seriennummer anonymisiert).

Beiträge sind willkommen – besonders Daten von anderen Speichern, mehreren Akkus oder
aktiven Alarmen.

## Danksagung

Diese Integration wäre ohne die Arbeit anderer Projekte nicht möglich gewesen – vielen Dank an
alle Entwicklerinnen und Entwickler dahinter!

| Projekt | Was wir davon haben |
|---|---|
| [Home Assistant – Tuya-Integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/tuya) | Der QR-Code-Login über die Smart-Life-App ist an deren Config-Flow angelehnt und nutzt denselben öffentlichen Client. |
| [tuya-device-sharing-sdk](https://github.com/tuya/tuya-device-sharing-sdk) von Tuya | Bibliothek für den Login und das Abholen von Geräte-ID und Local Key. |
| [tinytuya](https://github.com/jasonacox/tinytuya) von Jason Cox | Die gründlichste Dokumentation des lokalen Tuya-Protokolls (Frames, Session-Key-Handshake von 3.4, UDP-Discovery) – Grundlage für unseren eigenen asynchronen Protokoll-Client. |
| [LocalTuya](https://github.com/rospogrigio/localtuya) von rospogrigio und Mitwirkenden | Hat gezeigt, wie man Tuya-Geräte lokal in Home Assistant betreibt; damit wurde der Wake-Befehl für die Live-Daten gefunden und getestet. |
| [Xtend Tuya](https://github.com/azerty9971/xtend_tuya) von azerty9971 | Hat die Datenpunkte des Speichers überhaupt erst sichtbar gemacht – deren Diagnose war der Startpunkt fürs Entschlüsseln. |
| [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) von Matthew Flamm | Testumgebung für Custom Integrations. |
| [HACS](https://hacs.xyz) | Verteilung und Updates. |

Code aus LocalTuya, Xtend Tuya oder tinytuya wurde nicht übernommen; der Protokoll-Client
ist eine eigene Implementierung auf Basis der dort dokumentierten Protokolldetails.

## Hinweis

Dies ist ein privates Community-Projekt und steht in keiner Verbindung zu Powerness, EPP, DMEGC,
Tuya oder Home Assistant. Alle Marken gehören ihren jeweiligen Inhabern. Nutzung auf eigene Gefahr.

## Lizenz

[MIT](LICENSE)
