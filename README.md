*[English](README.en.md) · Русский*

# KNX Device Emulator

Симулятор виртуальных KNX-устройств. Эмулирует произвольное количество
устройств, которые ведут себя на шине как железные: реагируют на команды
(`GroupValueWrite`), отвечают на опрос (`GroupValueRead` → `Response`) и сами
рассылают статус при изменении состояния. Подключается к шине по **KNXnet/IP**
(tunneling к вашему IP-устройству или routing).

Дополнительно есть **интерфейс управления** — единый канал, через который можно
изменить состояние устройства «как будто локально» (как нажатие кнопки на
панели): устройство меняет состояние и само сообщает новый статус на шину.

## Установка и запуск

```bash
pip install -r requirements.txt
cp config.example.ini config.ini      # отредактируйте под своё окружение
python main.py --config config.ini
```

Ключи запуска: `--log-level DEBUG` — подробный лог; `--shutdown-timeout N` — сколько
секунд ждать штатного завершения после Ctrl+C (по умолчанию 3; повторный Ctrl+C
завершает сразу).

## Архитектура

```
config.ini ─▶ ConfigLoader ─▶ DeviceManager ◀─ DeviceRegistry ◀─ devices/*.py
                                   │  ▲
                  ControlInterface ┘  │  routes (GA→DataPoint)
                  (REST/CLI)          ▼
                                  BusAdapter ──KNXnet/IP──▶ шина KNX
```

| Слой | Модуль | Ответственность |
|------|--------|-----------------|
| Запуск | `main.py` | склейка компонентов, сигналы |
| Конфиг | `core/config_loader.py` | парсинг/валидация ini |
| Плагины | `core/registry.py` | авто-обнаружение устройств в `devices/` |
| Рантайм | `core/device_manager.py` | маршрутизация телеграмм GA→устройство |
| Шина | `core/bus_adapter.py` (`core/bus.py`) | мост к xknx; в тестах — фейк |
| Контракт | `core/device.py` | `BaseDevice`, `@local_command` |
| Точки данных | `core/datapoint.py` | Action/Status (group objects) |
| Кодеки | `core/dpt.py`, `core/address.py` | DPT и Group Address |
| Управление | `core/control/` | `ControlInterface` + транспорты |

Три источника изменения состояния, все ведут к рассылке статуса на шину:
1. **с шины** — `Write` на Action-адрес → `on_action()`;
2. **опрос** — `Read` на Status-адрес → `Response`;
3. **локально** — команда через `ControlInterface` → `@local_command`.

## Как добавить устройство (один файл)

Создайте `devices/my_device.py` с классом-наследником `BaseDevice`:

```python
from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL

class MyDevice(BaseDevice):
    TYPE = "my_device"                 # связь с config: type = my_device

    def setup(self):
        self._state = False
        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_action))
        self.status = self.add(
            StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, lambda: self._state))

    def on_action(self, value):        # команда с шины
        self._state = value
        self.publish(self.status)

    @local_command("toggle")           # команда с панели — обработка ЗДЕСЬ
    def cmd_toggle(self):
        self._state = not self._state
        self.publish(self.status)
        return self.state_snapshot()
```

Реестр подхватит его автоматически. В `config.ini` добавьте секцию: `type`
связывает её с плагином, остальные ключи — те, что устройство читает в
`setup()` (здесь это групповые адреса):

```ini
[lamp0]
type   = my_device
Action = 1/1/1        ; сюда приходит команда (GroupValueWrite)
Status = 2/1/1        ; отсюда читается и сюда рассылается статус
```

Вид телеграммы задаёт класс точки, настраивать его не нужно: `ActionPoint`
принимает запись и вызывает обработчик, `StatusPoint` отвечает на чтение и
рассылает значение при `publish()` и при старте.

### Свой тип данных (DPT)

Тип значения задаёт кодек DPT, который передаётся в точку. В ядре
(`core/dpt.py`) есть:

| Кодек | DPT | Значение |
|---|---|---|
| `DPT_BOOL` | 1.001 | бит; годится для любого однобитного типа (1.002, 1.008, 1.010 …) |
| `DPT_SCALING` | 5.001 | 0..100 % |
| `DPT_UCOUNT` | 5.010 | байт 0..255 |
| `DPT_TEMPERATURE` | 9.001 | °C |
| `DPT_AIR_QUALITY_PPM` | 9.008 | ppm |
| `DPT_CONCENTRATION_UGM3` | 9.030 | µg/m³ |

Если нужного нет, объявите его в том же файле устройства — ядро менять не нужно:

```python
from core.dpt import DPT
from core.exceptions import DPTError

class DPTPulses(DPT):
    main, sub = 7, 1                   # DPT 7.001: два байта без знака
    payload_kind = "array"

    def encode(self, value) -> bytes:  # значение Python -> посылка на шину
        v = int(value)
        if not 0 <= v <= 0xFFFF:
            raise DPTError(f"7.001 out of range 0..65535: {v}")
        return bytes([v >> 8, v & 0xFF])

    def decode(self, raw) -> int:      # посылка с шины -> значение Python
        if len(raw) < 2:
            raise DPTError("7.001: 2 bytes expected")
        return (raw[0] << 8) | raw[1]

DPT_PULSES = DPTPulses()               # передаётся в точку вместо DPT_BOOL
```

`payload_kind` определяет вид посылки: `"binary"` — значение до 6 бит, `encode`
возвращает `int`, `decode` получает `int`; `"array"` — один или несколько байт,
`encode` возвращает `bytes`, `decode` получает `bytes`. Так объявлены 20.105 и
1.100 в `devices/thermostat.py`. Тип, нужный нескольким устройствам, лучше
положить в `core/dpt.py`.

## Устройства

| `type` | Объекты на шине | Команды с панели | Примечание |
|---|---|---|---|
| `outlet` | `Action` / `Status` (DPT 1.001) | `toggle`, `set on=` | `Inverted` инвертирует состояние относительно шины |
| `dimmer` | `Action` / `Status` (1.001), `ActionDim` / `StatusDim` (5.001) | `toggle`, `set_level level=` | |
| `thermostat` | уставка и текущая температура (9.001), режим (20.105), On/Off (1.001), сезон (1.100) | `set_onoff on=`, `set_mode mode=`, `set_setpoint value=`, `set_current value=`, `set_season season=` | см. раздел ниже |
| `air_conditioner` | всё от `thermostat` и вентилятор `ActionFan` / `StatusFan` (5.001, 0..100 %) | те же и `set_fan level=` | |
| `fan` | `ActionFan` / `StatusFan` — номер ступени одним байтом (5.010) | `set_speed speed=`, `off` | `Speeds` — число ступеней, 1..4; ступень выше последней отбрасывается |
| `fan_relay` | `ActionSpeedN` / `StatusSpeedN` — реле на каждую ступень (1.001) | `set_speed speed=`, `off` | проверяет алгоритм актуатора: сначала выключить все обмотки, потом включить нужную; нарушения пишутся в лог как ошибки |
| `air_quality_sensor` | только статусы: `StatusAQI` (5.010), `StatusCO2` / `StatusTVOC` / `StatusCH2O` (9.008), `StatusPM1` / `StatusPM2_5` / `StatusPM10` (9.030) | `<датчик> set=`, например `co2 set=400` | работает тот датчик, чей адрес задан; `CycleSec` — период циклической рассылки |
| `garage_door` | `Action` (1.008) или пара `ActionOpen` / `ActionClose`; статусы — бит, проценты, два датчика | `open`, `close`, `stop` | см. раздел ниже |
| `shutter` | `Movement` (1.008), `Stop` (1.010), `TargetPosition` / `CurrentPosition` (5.001), `StatusMovement` (1.008) | `up`, `down`, `stop`, `position percent=` | `0 %` = открыто, `100 %` = закрыто; позиция сообщается, когда привод остановился |

Все ключи конфигурации с примером секции для каждого типа — в
`config.example.ini`; поведение устройства описано в начале его файла
(`devices/*.py`).

## Термостат / кондиционер: режимы

Целевой режим приходит только на `ActionMode` (DPT 20.105), текущий режим
(`StatusMode`) его зеркалит:

| Значение на шине | Режим | Поведение |
|---|---|---|
| 1 | `off`  | прибор выключен (`StatusOnOff` = 0) |
| 2 | `heat` | нагрев до `Setpoint` |
| 3 | `cool` | охлаждение до `Setpoint` |
| 4 | `auto` | прибор сам выбирает нагрев или охлаждение |

`On/Off` и режим равноценны: `mode = off` выключает прибор, а `On/Off = on`
восстанавливает последний активный режим (в т.ч. `auto`).

**AUTO** сравнивает текущую температуру с целевой: ниже `Setpoint - AutoHysteresis`
— греет, выше `Setpoint + AutoHysteresis` — охлаждает, внутри зоны простаивает;
начатый нагрев/охлаждение идёт до `Setpoint` (гистерезис против дребезга).
На шину при этом уходит именно `auto`, выбранное направление видно в состоянии
панели как `auto_action`.

**AUTO доступен, только если не активирован сезонный режим** — то есть в секции
устройства нет `StatusSeason`/`Season`. При заданном сезоне направление уже
задано жёстко (лето → только `cool`, зима → только `heat`), поэтому команда
`auto` с шины или с панели игнорируется (с записью в лог).

## Гаражные ворота: время хода и варианты статуса

Тип `garage_door`. По умолчанию орган управления — бит `Action` (DPT 1.008):
`0` = открыть (Up), `1` = закрыть (Down); `Inverted = True` меняет их местами
(импульсные и релейные приводы — в подразделе «Варианты привода»).
Как настоящий привод, ворота едут `TravelSec` секунд от одного крайнего
положения до другого. Встречная команда во время движения разворачивает ворота
из текущей виртуальной позиции — остаток пути занимает пропорциональное время.
Команда в ту же сторону (или «открыть» уже открытым воротам) игнорируется без
телеграмм, только со строкой в логе.

Статус можно отдавать тремя способами, все они **необязательны и независимы**:
работает тот, чей групповой адрес задан в конфиге (хоть все три сразу).

| Ключ | DPT | Поведение |
|---|---|---|
| `Status` | 1.008 | один бит, следует семантике команды: `1` = закрыто (при `Inverted` — `1` = открыто). Обновляется только в крайних положениях |
| `StatusPosition` | 5.001 | `0 %` = закрыто, `100 %` = открыто (`InvertedPosition = True` переворачивает шкалу). Обновляется только в крайних положениях |
| `SensorOpened` / `SensorClosed` | 1.002 | два концевых датчика, `1` = ворота стоят у этого края (`InvertedSensorOpened` / `InvertedSensorClosed = True`: у края `0`, как нормально замкнутый контакт) |

Последовательность датчиков при открытии из закрытого состояния:

| Момент | `SensorOpened` | `SensorClosed` |
|---|---|---|
| закрыто | 0 | 1 |
| начали открывать | 0 | 0 (телеграмма `SensorClosed` → 0) |
| едут | 0 | 0 |
| полностью открыты | 1 (телеграмма `SensorOpened` → 1) | 0 |

Команды с панели: `open`, `close` (то же, что команда с шины) и `stop` —
остановка на полпути: оба датчика остаются `0`, бит и проценты продолжают
показывать последнее достигнутое крайнее положение. Следующая команда
`open`/`close` едет из точки остановки.

```ini
[garage0]
type           = garage_door
Action         = 1/7/1     ; команда (DPT 1.008)
Status         = 2/7/1     ; бит (необязательно)
StatusPosition = 2/7/2     ; проценты (необязательно)
SensorOpened   = 2/7/3     ; датчик «открыто» (необязательно)
SensorClosed   = 2/7/4     ; датчик «закрыто» (необязательно)
TravelSec      = 15        ; время полного хода, с (по умолчанию 10)
State          = closed    ; начальное состояние: closed | open
Inverted       = False     ; True: команда 1 = открыть, бит-статус 1 = открыто
InvertedPosition     = False   ; True: 0 % = открыто, 100 % = закрыто
InvertedSensorOpened = False   ; True: SensorOpened = 0, когда ворота полностью открыты
InvertedSensorClosed = False   ; True: SensorClosed = 0, когда ворота полностью закрыты
Impulse        = False     ; True: телеграмма во время движения останавливает привод
PushButton     = False     ; True: Action — кнопка привода, значение бита не важно
```

### Варианты привода

По умолчанию эмулируется мотор: бит задаёт направление. Для других приводов:

| Настройка | Поведение |
|---|---|
| `Impulse = True` | привод со стоп-состоянием: телеграмма во время движения останавливает ворота на месте (как `stop`), телеграмма стоящим воротам двигает их, как просит бит |
| `PushButton = True` | `Action` — кнопка привода, значение бита не важно. В крайнем положении нажатие уводит ворота от этого края, после остановки на полпути — в обратную сторону. Нажатие на ходу разворачивает ворота, а вместе с `Impulse = True` останавливает их: циклы «открыть → закрыть» и «открыть → стоп → закрыть → стоп» |
| `ActionOpen` + `ActionClose` | два импульсных канала вместо `Action`: любая телеграмма на `ActionOpen` открывает, на `ActionClose` закрывает, значение не важно. Адреса задаются только парой, `Action` при этом не используется, `Impulse` и `PushButton` на два канала не влияют. Дальше действуют те же правила, что и для бита: встречная команда разворачивает, повтор игнорируется |

```ini
[garage_relays]
type         = garage_door
ActionOpen   = 1/7/8       ; импульс «открыть»
ActionClose  = 1/7/9       ; импульс «закрыть»
SensorOpened = 2/7/3
SensorClosed = 2/7/4
```

## Интерфейс управления (REST)

```
GET  /devices                      # список устройств + состояние
GET  /devices/{name}               # состояние + доступные команды
POST /devices/{name}/commands      # {"command": "set", "args": {"on": true}}
```

Пример:
```bash
curl -X POST localhost:8080/devices/outlet0/commands \
     -H 'Content-Type: application/json' \
     -d '{"command":"toggle"}'
```

### CLI (transport = cli)

REPL в консоли с **TAB-автодополнением** (на базе `prompt_toolkit`): TAB
показывает доступные на текущем уровне варианты с описанием справа —
устройства → команды устройства → аргументы `ключ=` и подсказки значений.

```
knx> <device> <command> [key=value ...]      # формат команды
knx> outlet0 toggle
knx> thermostat_room set_mode mode=heat
knx> thermostat_room set_mode mode=auto        # сам выберет нагрев/охлаждение
knx> thermostat_room set_onoff on=true
knx> list | describe <dev> | help | quit      # служебные
```

Если stdin не TTY (ввод из пайпа) — автодополнение отключается, работает
простой построчный ввод.

## Тесты

```bash
pytest                 # вся логика тестируется на FakeBusAdapter, без сети
```
