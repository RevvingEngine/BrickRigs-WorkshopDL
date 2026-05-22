# BrickRigs-WorkshopDL
## Моды для BR через WorkshopDL

> [!IMPORTANT]
> AI slop!

Содержание:
- Скрипт
- Расширение для Firefox

### Скрипт
Для запуска скрипта нужно в папке с скриптом запустить cmd.

У скрипта есть 4 режима:

fix-workshop (основной режим для WorkshopDL-папок)
```
python brickrigs_fixer.py fix-workshop
  --dir "dir/i/guess/Vehicles" # путь к папке с сейвами
  --template "path/maybe/MetaData.brm"  # путь к Metadata.brm (на случай если все-таки надо)
  --no-rename # не переименовывать папки, только патчить файлы
  --dry-run # только показать что будет сделано, ничего не менять
```

fix-all (фиксит онли метадату,юберет назву папки за основу)
```
python brickrigs_fixer.py fix-all
  --dir "dir/i/guess/Vehicles"
  --skip "_template"   # пропустить конкретную папку
  --dry-run
```
inspect (посмотреть что внутри конкретного файла)
```
python brickrigs_fixer.py inspect --file "MetaData.brm"
```
patch (поменять назву в одном файле)
```
python brickrigs_fixer.py patch
  --file "MetaData.brm"
  --title "абвгд1234"
  --desc "цукерка ромашка класична"
  --out "MetaData_new.brm"   # если не указать --out, перезапишет оригинал
```

### Расширение
Это расширение которое делает списки модов для WorkshopDL.
На каждую страницу добавлена кнопка Add to WorkshopDL,при нажимании она добавляет страницу в список,который можно очистить,скопировать или скачать.
Расширение импортируется через about:debugging в самом Firefox,потому что ну вот так вот

### Код можете брать или переделывать и перезаливать даже без указания автора,ии слоп энивей
