# Аудит локального исполнения Bloodborne — 2026-09-08

Primary item: **BB-ENV1**, bounded feasibility audit. Проверен checkout
`c615ce4d767e18a13331ab50b30ce68d54024f93` этого репозитория.
Все выводы ниже относятся к этому состоянию, а не к незамерженным PR.

## Вывод для ROADMAP

Агент имеет доступ к локальному target и рабочей X11-сессии `:1`.
Прежнее наблюдение «в cloud checkout только synthetic target» остаётся верным
для содержимого Git, но больше не описывает доступные этому агенту ресурсы.
Переносить все runtime items в `CLOUD` или объявлять их выполненными нельзя:
ограничителями стали provenance, допустимость build/config, semantic oracles
и незавершённая instrumentation, а не само отсутствие target machine.

В текущем ROADMAP **нет items с execution `LOCAL ONLY`**. Все 14 target-run
items используют `GATED`; это не утверждение об их невозможности в cloud.
Статусы и dependency graph этим аудитом не закрываются и не перестраиваются.

## Проверенные исходные данные

| Наблюдение | Evidence / граница |
|---|---|
| Ubuntu 24.04.3 LTS; Linux `7.0.0-31-generic`, x86_64; AMD Ryzen 9 7945HX3D, 32 logical CPUs | Текущие `os-release`, `uname`, `lscpu`; `runtime` host capability |
| NVIDIA GeForce RTX 5070 Ti, driver `595.84`, 16303 MiB | `nvidia-smi` текущего host; это не measurement VRAM usage игры |
| `DISPLAY=:1 xdpyinfo` успешен, X.Org 1.21.1.11; `xwininfo` перечисляет окна | `runtime`; X connection работает с унаследованной авторизацией; секреты/desktop capture не публикуются |
| В начале аудита shadPS4 process отсутствовал | `ps`; пользователь сообщил о предыдущем запуске (`reported`) |
| В указанном каталоге `emus` один AppImage | `static`; basename/имя каталога не удостоверяет исходный commit |
| GDB, X11 inspection, `xwd`, Pillow и `bwrap` установлены | Наличие инструментов; input injection/RenderDoc capture не проверены; неуспешный debugger attach описан ниже |
| `bwrap` control `/bin/true` отклонён | `No permissions to create new namespace`; использована копия target, а не изменение kernel/security policy |
| `vulkaninfo`, `renderdoccmd`, `xdotool` отсутствуют в PATH | Не доказательство недоступности проекту. `apt-cache` предлагает `vulkan-tools 1.3.275.0+dfsg1-1`; установка необязательна для этого аудита и не выполнялась |

Локальный `Shadps4-sdl.AppImage`: 35326456 bytes,
SHA-256 `70693665d2aed2281bd86b0b727eb1174328d09b5e0e9b7d1c9212f8fc598d0f`.
Извлечённый ELF: SHA-256
`bed84281e733d0260acfb248cee7a56282ca1c9157db5578216b3e70736f0c88`.
`AppRun --help` завершился успешно; доступны `--game`, `--override-root`,
`--config-clean`, `--ignore-game-patch`, `--wait-for-debugger`, `--show-fps`.
Наличие этих flags не доказывает работоспособность debugger/telemetry.

Основной target: `CUSA03173`, CONTENT_ID
`EP9000-CUSA03173_00-BLOODBORNE0000EU`; `APP_VER=01.00`, `VERSION=01.00`.
Значения прочитаны непосредственно из PSF/SFO index (`static`).

- `eboot.bin`: 93827832 bytes, SHA-256
  `6764938b23539d29c936bca9880fc4a774e7b0099ce31c7e8c4b0f8bd0befb80`.
- `sce_sys/param.sfo`: SHA-256
  `312d6e3068893dae46d871575498ef53b7160e60adb30282ef88da0a5deb60f2`.
- Соседняя папка `CUSA03173-UPDATE`: SFO сообщает тот же title/content ID,
  `APP_VER=01.09`, `VERSION=01.00`; SFO SHA-256
  `7c998973e4ab800f1cc6c2a73e2739ca1a5def8d1af254efd3f8cf91202f419d`.

Это **два разных входа**, а не доказательство effective update state. Аудит
не выдаёт base-tree hash за полный resolved base+update+DLC manifest.
Происхождение заменённых файлов/встроенных mods неизвестно; SFO version
сама по себе не доказывает stock/unmodified identity.

## Предыдущий запуск: отдельный класс evidence

Прочитан существовавший до эксперимента локальный журнал. Он сообщает
`v0.18.0`, revision `e3ce810f3a653f43ac64ebab63023de281a4103a`, remote
`https://github.com/shadps4-emu/shadPS4`, загрузку `CUSA03173`, создание Vulkan
device NVIDIA RTX 5070 Ti (`595.84.0.0`, Vulkan `1.4.329`), вызовы игрового
потока и регистрацию трёх VideoOut buffers `1920×1080`, `A8R8G8B8Srgb`.
Есть сообщения о ненайденных файлах и stubbed APIs. Они не устанавливают
ни root cause, ни корректность/некорректность финального изображения.

Это `static` inspection прежнего runtime log, **reported historical runtime**:
нет связанного current-run manifest, полного config/target identity и
checkpoint oracle. Self-reported revision не равен независимой
source→binary attestation. Журнал не публикуется: содержит private paths и
детали target, не нужные для обзора.

## Почему supported BB-ENV1 run пока заблокирован

Текущий [контракт](target-execution-feasibility.md) допускает Linux AppImage
SHA-256 `7c6512eb2bced183bbda2fe858c503c2a4d6cc3146648f2c859a0477403fbd75`,
35179000 bytes, из BB-BL1
`shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`.
Локальный бинарник не совпадает ни по размеру, ни по digest.

Проверен GitHub API artifact `9198177755`, workflow `31742892228`:
`expired=true`; реальный запрос `/actions/artifacts/9198177755/zip`
получил **HTTP 410, `Artifact has expired`**. В проверенных деревьях
`shadps4` и job storage совпадающего artifact не найдено. Это ограниченный
поиск, не утверждение об отсутствии всех внешних архивных копий.

Самостоятельная пересборка не гарантирует exact accepted bytes; подмена
pin локальным digest обошла бы текущий contract. Следующий шаг — получить
архивную копию именно pinned artifact и проверить committed digest, либо
отдельно принять полноценный source/build provenance route. Ни просьба
«включить GUI», ни установка Vulkan tools не исправляет HTTP 410.

Во время аудита уже открыт [PR #127](https://github.com/kaaburgh/bb-shadPS4-correctness-instrumentation/pull/127)
на patched-build route (проверенный head
`2ee4484a7d1b9b10459927716ab3b261e810e662`), а
[PR #80](https://github.com/kaaburgh/bb-shadPS4-correctness-instrumentation/pull/80)
отражает config/patch provenance blockers в roadmap. Они не входят в
проверенный baseline; аудит не дублирует их реализацию и не предполагает merge.
Даже принятие patched route не восстанавливает неизвестное происхождение
локального UltraPersona автоматически.

## Отдельный ограниченный launch probe

Это диагностическая попытка по запросу пользователя, **не** запуск через
`tools/run_target_experiment.py`, не `bb-target-run/v3`, не acceptance BB-ENV1.
[Одноразовый probe](local-environment-audit-probe.py) сохранён для review.
Он требует заранее проверенную disposable копию; сам не удостоверяет
source→binary связь и не заменяет supported runner.

Перед запуском все regular files выбранной base-папки скопированы с
независимым SHA-256 чтением source и destination; symlinks/nonregular files
отклоняются. Соседний update, пользовательские saves/config/patches в эту
копию не включаются. Выбран именно явно указанный base target; такой
эксперимент не является воспроизведением предыдущего effective setup.

Probe создаёт новый portable `user` и отдельные XDG data/config/cache paths,
оставляет HOME и исходную установку без переназначения, использует `DISPLAY=:1`
и существующую X11 авторизацию. `--override-root` указывает на копию,
`--config-clean --ignore-game-patch --fullscreen false` задают диагностический
режим. Каждый run без input injection: 60 s deadline, TERM/KILL process group,
два cleanup waits максимум по 3 s, core dumps отключены, каждый output file
ограничен 32 MiB. Это bounded process-group cleanup, не sandbox против
произвольного кода/отделившихся daemon processes.

Заранее заданный результат проверки: зафиксировать фактическую стадию
инициализации, ошибку/exit либо timeout. Окно/логи/liveness сами по себе
не принимаются за title menu или gameplay. Семантический checkpoint остаётся
`unassessed`, пока нет независимого наблюдения именно этого состояния.

Воспроизводимый invocation после identity-verified copy и AppImage extraction:

```sh
export DISPLAY=:1
python3 docs/experiments/local-environment-audit-probe.py \
  --app-run "$AUDIT_EXTRACTED_APP/AppRun" \
  --target-copy "$AUDIT_VERIFIED_BASE_COPY" \
  --work "$AUDIT_NEW_PRIVATE_WORK"
```

Переменные обозначают отдельные operator-selected disposable paths;
`--work` должен ещё не существовать. Raw output и target bytes не коммитятся.

## Результат новых запусков

Выполнены **две** попытки с одинаковыми inputs/flags и разными новыми
профилями. Первая проверяла прямой запуск; вторая добавлена после таймаута
для ограниченной попытки debugger observation. Первая длилась **60.007 s**,
вторая **60.005 s**; обе завершены probe по deadline, return code **-15**
(SIGTERM), `timed_out=true`. После cleanup shadPS4 process не обнаружен.

В обеих stdout содержит только начальную строку `main.cpp:145 main: Run`;
игровой `shad_log.txt` не появился. X11 polling первой попытки не обнаружил
окна shadPS4/Bloodborne. Таким образом, ни menu, ни gameplay, ни Vulkan
initialization **в этих попытках не установлены**. Backend/GPU из старого
журнала не переносятся в новый run record. Точная причина остановки неизвестна;
различия чистого профиля, первого запуска и контекста агента остаются
гипотезами. Это не доказательство, что пользователь не запускал игру.

Первый поздний GDB attach застал уже завершённый процесс (`No such process`).
Во второй попытке `timeout 10 gdb -q -nx -batch ... -p <probe-pid>` получил
`ptrace: Inappropriate ioctl for device` и не собрал стек.
`kernel.yama.ptrace_scope=1`; этого недостаточно, чтобы приписать отказ
единственно Yama. Изменение security policy/sudo не выполнялось. Следующий
ограниченный диагностический шаг — разрешённый parent-debugger launch либо
контроль с отдельно проверенной копией конфигурации прежнего запуска; это
дальнейшая диагностика, а не условие признания данного аудита завершённым.

Проверенный base-tree digest (`sha256-tree-v1`, namespace `app/`):
`212a0643e0506f1d863f33ae761d41710fe0a746a26a15a95ff0fe0777b719c3`,
**28831 files / 31513388908 bytes**. Независимое чтение source и copy
подтвердило равенство до запуска. Время копирования/проверки **201.1 s** —
это overhead подготовки, не скорость эмуляции. Полное повторное хеширование
исходной base-папки после запуска подтвердило тот же digest: source tree
не изменился.

[Безопасная запись аудита](local-environment-audit-2026-09-08.json) имеет
schema `bb-local-environment-audit/v1`, hash probe/target/binary, host identity,
scenario flags, limits, termination и explicit unknowns. Это curated audit
record, **не** совместимый вход downstream `bb-target-run/v3` consumers.
Raw logs остались private; в JSON сохранены только их digests/размеры.
Запись не включает paths, usernames, credentials, файлы игры или screenshots.

## Реализуемость по items

| Items | Что изменилось / конкретный оставшийся gate |
|---|---|
| BB-ENV1 | Host/target доступны агенту. Сначала восстановить допустимый artifact или принять build provenance route; затем validated target manifest и supported bounded run. Статус остаётся `Implemented, validation incomplete`. |
| BB-BL4 | Локально можно исследовать startup/gameplay candidates после ENV1. Для `selected` нужны 3–6 scenarios и semantic checkpoint evidence; нынешний `process-exit` недостаточен. |
| BB-BL6 | Повторные local runs физически возможны; BL4 и runtime telemetry не готовы. BB-BL5 сейчас пакует пять `unavailable` metrics — повторение этого packer не создаёт baseline distributions. |
| BB-COR2 | GPU присутствует; дальше нужны scene oracle и render/depth/shader/resource descriptors на идентифицированном build. GUI не заменяет их. Сохраняются ENV1/BL6/COR1 dependencies. |
| BB-COR3 | Локальный GPU позволяет будущую VRAM/lifetime диагностику. `nvidia-smi` inventory не отличает leak, cache и delayed destruction; нужны correlated allocation/lifetime events. |
| BB-COR4 | Возможен будущий bounded CPU/GPU run; нужны ordering/readback events и resource IDs, а не только кадры/время. |
| BB-COR5 | Доступен один проверенный host/driver setup. Можно воспроизводить конкретный crash; broad hardware/backend matrix здесь не установлена. |
| BB-FIX2, BB-FIX4, BB-FIX6 | Сохраняются semantic-seam dependencies. Текущий runner отвергает patched binary/config; сначала provenance route и объективный regression oracle. Локальная машина не доказывает нужду в title-specific workaround. |
| BB-INS4 | Host пригоден для будущего off/on эксперимента, но INS2/INS3 ещё partial. Нужны admitted instrumented build, direct-CPU coverage control и bounded trace producer; ни наличие GPU, ни FPS overlay не закрывает coverage/overhead. |
| BB-SHD2, BB-RES2, BB-PERF2 | Возможная последующая local collection. Сохраняются COR7/INS4 и собственные schema/model dependencies. Не собирать optimization-ranking corpus до correctness gate; разрешённый co-capture не отменяет независимую validity каждого artifact class. |

Cloud research/analysis items не становятся blocked из-за местоположения:
BB-INS2/INS3 static/synthetic work может продолжаться; BB-FIX1/3/5,
BB-SHD1/3, BB-RES1/3, BB-PERF1/3, BB-COR6/7 и BB-SPEC1 сохраняют свои
evidence dependencies. Обходить их потому, что теперь доступен display, нельзя.

## Рекомендации и границы этого PR

1. Обновить **только evidence/next step BB-ENV1**: target-owning host уже
   доступен агенту; named blocker — expired pinned build и незавершённая
   identity/admission, а не отсутствие graphics session. Сохранить прошлый
   negative result и незакрытый acceptance.
2. После provenance admission выбрать явно base `01.00` или resolved `01.09`,
   собрать полный BB-BL2 manifest (включая overlays/config/mod set), использовать
   immutable view/verified copy и supported runner. Не применять bare folder
   labels как exact source/target identity.
3. Отдельными bounded изменениями связать consumed configuration, semantic
   capture producer и telemetry с текущим run. Эти работы нужны до selected
   BL4 и measured BL6; положительный ENV1 `process-exit` их не заменяет.
4. Согласовать patched-build изменения с PR #127, config consequences — с
   PR #80; текущий аудит не меняет admission implementation.
5. Затем BL4 → BL6 → per-class correctness; instrumentation work может
   продолжаться независимо в рамках явных dependencies. COR7 и INS4
   остаются hard gates для post-correctness collection.

Отдельной поддерживаемой operator checklist/projection среди tracked files
не найдено. Актуальная процедура отражена в
[target-execution-feasibility.md](target-execution-feasibility.md), а planning
state остаётся только в [ROADMAP](../../ROADMAP.md).

Не выполнялись: gameplay control, успешный debugger attachment, RenderDoc capture,
correctness regression, profiling, instrumentation off/on, hardware matrix,
full updated-target manifest или BB-ENV1 acceptance run. Не менялись
пользовательские сохранения, installed target/config, upstream source и
правила provenance. Наличие доступного инструмента не представлено как
проверенная target capability.


## Проверки репозитория

- `python3 -m py_compile docs/experiments/local-environment-audit-probe.py`
  прошёл; probe также реально выполнен дважды. Это проверка bounded
  diagnostic mechanism, не тест correctness игры.
- `git diff --check` прошёл.
- Получен именно lock-pinned `agentic-repo-kit-0.1.13.pyz`; SHA-256
  `b1b7b23f1082dd3998cf01f6335a571aa695eb422a99aa1809e8e5770317c985`
  совпал с `.agentic-repo.lock.json`.
- `python3 /path/to/verified/agentic-repo-kit-0.1.13.pyz check .` проверяет
  managed-file consistency, relative links и roadmap graph; после всех
  изменений получено `agentic repository contract is consistent`. В этом host используется `python3`, поскольку
  alias `python` отсутствует.
- Полный unit suite не запускался: runner/schema/production code не менялись;
  для нового observational probe выполнены syntax и реальные bounded runs.
