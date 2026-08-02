*[English](README.en.md) · Русский · [Deutsch](README.de.md)*

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

Реестр подхватит его автоматически. В `config.ini` добавьте секцию с `type = my_device`.

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
