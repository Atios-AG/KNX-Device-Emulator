*[English](README.en.md) · [Русский](README.md) · Deutsch*

# KNX Device Emulator

Ein Simulator virtueller KNX-Geräte. Er emuliert beliebig viele Geräte, die
sich auf dem Bus wie echte Hardware verhalten: Sie reagieren auf Befehle
(`GroupValueWrite`), beantworten Abfragen (`GroupValueRead` → `Response`) und
senden ihren Status bei jeder Zustandsänderung selbstständig auf den Bus. Die
Anbindung an den Bus erfolgt über **KNXnet/IP** (Tunneling zu Ihrem IP-Gerät
oder Routing).

Zusätzlich gibt es eine **Steuerschnittstelle** — einen einheitlichen Kanal,
über den sich der Zustand eines Geräts „wie lokal“ ändern lässt (wie ein
Tastendruck am Bedienpanel): Das Gerät ändert seinen Zustand und meldet den
neuen Status selbst auf den Bus.

## Installation und Start

```bash
pip install -r requirements.txt
cp config.example.ini config.ini      # an die eigene Umgebung anpassen
python main.py --config config.ini
```

## Architektur

```
config.ini ─▶ ConfigLoader ─▶ DeviceManager ◀─ DeviceRegistry ◀─ devices/*.py
                                   │  ▲
                  ControlInterface ┘  │  routes (GA→DataPoint)
                  (REST/CLI)          ▼
                                  BusAdapter ──KNXnet/IP──▶ KNX-Bus
```

| Schicht | Modul | Verantwortung |
|---------|-------|---------------|
| Start | `main.py` | Verdrahtung der Komponenten, Signale |
| Konfiguration | `core/config_loader.py` | Parsen/Validieren der ini |
| Plugins | `core/registry.py` | automatisches Finden der Geräte in `devices/` |
| Laufzeit | `core/device_manager.py` | Telegramm-Routing GA→Gerät |
| Bus | `core/bus_adapter.py` (`core/bus.py`) | Brücke zu xknx; in den Tests ein Fake |
| Vertrag | `core/device.py` | `BaseDevice`, `@local_command` |
| Datenpunkte | `core/datapoint.py` | Action/Status (Gruppenobjekte) |
| Codecs | `core/dpt.py`, `core/address.py` | DPT und Gruppenadresse |
| Steuerung | `core/control/` | `ControlInterface` + Transporte |

Drei Quellen einer Zustandsänderung, alle führen zu einer Statusmeldung auf dem
Bus:
1. **vom Bus** — ein `Write` auf die Action-Adresse → `on_action()`;
2. **Abfrage** — ein `Read` auf die Status-Adresse → `Response`;
3. **lokal** — ein Befehl über das `ControlInterface` → `@local_command`.

## Ein Gerät hinzufügen (eine einzige Datei)

Legen Sie `devices/my_device.py` mit einer von `BaseDevice` abgeleiteten Klasse
an:

```python
from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL

class MyDevice(BaseDevice):
    TYPE = "my_device"                 # Verbindung zur config: type = my_device

    def setup(self):
        self._state = False
        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_action))
        self.status = self.add(
            StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, lambda: self._state))

    def on_action(self, value):        # Befehl vom Bus
        self._state = value
        self.publish(self.status)

    @local_command("toggle")           # Befehl vom Panel — Behandlung HIER
    def cmd_toggle(self):
        self._state = not self._state
        self.publish(self.status)
        return self.state_snapshot()
```

Die Registry findet es automatisch. Fügen Sie in `config.ini` einen Abschnitt
mit `type = my_device` hinzu.

## Thermostat / Klimagerät: die Betriebsarten

Die Soll-Betriebsart kommt ausschließlich auf `ActionMode` (DPT 20.105) an, die
aktuelle Betriebsart (`StatusMode`) spiegelt sie:

| Wert auf dem Bus | Betriebsart | Verhalten |
|---|---|---|
| 1 | `off`  | Gerät ausgeschaltet (`StatusOnOff` = 0) |
| 2 | `heat` | Heizen bis `Setpoint` |
| 3 | `cool` | Kühlen bis `Setpoint` |
| 4 | `auto` | Gerät wählt Heizen oder Kühlen selbst |

`On/Off` und die Betriebsart sind gleichwertig: `mode = off` schaltet das Gerät
aus, `On/Off = on` stellt die zuletzt aktive Betriebsart wieder her (auch
`auto`).

**AUTO** vergleicht die aktuelle Temperatur mit der Solltemperatur: unterhalb
von `Setpoint - AutoHysteresis` wird geheizt, oberhalb von
`Setpoint + AutoHysteresis` gekühlt, innerhalb des Bandes bleibt das Gerät
untätig; ein begonnenes Heizen/Kühlen läuft bis `Setpoint` durch (Hysterese
gegen Flattern). Auf den Bus geht dabei genau `auto`, die gewählte Richtung ist
im Panel-Zustand als `auto_action` sichtbar.

**AUTO steht nur zur Verfügung, wenn der Saisonbetrieb nicht aktiviert ist** —
das heißt, im Geräteabschnitt gibt es kein `StatusSeason`/`Season`. Bei
gesetzter Saison ist die Richtung bereits fest vorgegeben (Sommer → nur `cool`,
Winter → nur `heat`), deshalb wird ein `auto`-Befehl vom Bus oder vom Panel
ignoriert (mit einem Log-Eintrag).

## Garagentor: Laufzeit und Statusvarianten

Typ `garage_door`. Das einzige Steuerobjekt ist das Bit `Action` (DPT 1.008):
`0` = öffnen (Auf), `1` = schließen (Ab); `Inverted = True` vertauscht beide.
Wie ein echter Antrieb braucht das Tor `TravelSec` Sekunden von einer
Endlage zur anderen. Ein Gegenbefehl während der Fahrt kehrt das Tor aus der
aktuellen virtuellen Position um — der Rest der Fahrt dauert proportional
lange. Ein Befehl in dieselbe Richtung (oder „öffnen“ für ein bereits offenes
Tor) wird ohne Telegramm ignoriert, nur mit einer Zeile im Log.

Der Status kann auf drei Arten gemeldet werden, alle **optional und
unabhängig**: Aktiv ist die Variante, deren Gruppenadresse in der Konfiguration
gesetzt ist (jede Kombination, auch alle drei gleichzeitig).

| Schlüssel | DPT | Verhalten |
|---|---|---|
| `Status` | 1.008 | ein Bit, folgt der Befehlssemantik: `1` = geschlossen (mit `Inverted` — `1` = offen). Nur in den Endlagen aktualisiert |
| `StatusPosition` | 5.001 | `0 %` = geschlossen, `100 %` = offen. Nur in den Endlagen aktualisiert |
| `SensorOpened` / `SensorClosed` | 1.002 | zwei Endlagensensoren, `1` = das Tor steht an dieser Endlage |

Sensorabfolge beim Öffnen aus der geschlossenen Stellung:

| Moment | `SensorOpened` | `SensorClosed` |
|---|---|---|
| geschlossen | 0 | 1 |
| Öffnen begonnen | 0 | 0 (Telegramm `SensorClosed` → 0) |
| fährt | 0 | 0 |
| ganz offen | 1 (Telegramm `SensorOpened` → 1) | 0 |

Befehle vom Panel: `open`, `close` (wie der Busbefehl) und `stop` — Halt auf
halbem Weg: Beide Sensoren bleiben `0`, Bit und Prozentwert melden weiterhin
die zuletzt erreichte Endlage. Das nächste `open`/`close` fährt vom Haltepunkt
aus weiter.

```ini
[garage0]
type           = garage_door
Action         = 1/7/1     ; Befehl (DPT 1.008)
Status         = 2/7/1     ; Bit (optional)
StatusPosition = 2/7/2     ; Prozent (optional)
SensorOpened   = 2/7/3     ; Sensor „offen“ (optional)
SensorClosed   = 2/7/4     ; Sensor „geschlossen“ (optional)
TravelSec      = 15        ; volle Laufzeit, s (Standard 10)
State          = closed    ; Anfangszustand: closed | open
Inverted       = False
```

## Steuerschnittstelle (REST)

```
GET  /devices                      # Liste der Geräte + Zustand
GET  /devices/{name}               # Zustand + verfügbare Befehle
POST /devices/{name}/commands      # {"command": "set", "args": {"on": true}}
```

Beispiel:
```bash
curl -X POST localhost:8080/devices/outlet0/commands \
     -H 'Content-Type: application/json' \
     -d '{"command":"toggle"}'
```

### CLI (transport = cli)

Eine REPL in der Konsole mit **TAB-Vervollständigung** (auf Basis von
`prompt_toolkit`): TAB zeigt die auf der aktuellen Ebene verfügbaren Optionen
mit einer Beschreibung rechts daneben — Geräte → Befehle des Geräts →
Argumente `schlüssel=` und Werthinweise.

```
knx> <device> <command> [key=value ...]      # Befehlsformat
knx> outlet0 toggle
knx> thermostat_room set_mode mode=heat
knx> thermostat_room set_mode mode=auto        # wählt Heizen/Kühlen selbst
knx> thermostat_room set_onoff on=true
knx> list | describe <dev> | help | quit      # eingebaute Befehle
```

Ist stdin kein TTY (Eingabe aus einer Pipe), wird die Vervollständigung
deaktiviert und einfache zeilenweise Eingabe verwendet.

## Tests

```bash
pytest                 # die gesamte Logik wird am FakeBusAdapter getestet, ohne Netzwerk
```
