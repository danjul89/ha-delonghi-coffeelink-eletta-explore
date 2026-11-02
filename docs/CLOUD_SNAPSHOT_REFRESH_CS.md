# Obnova cloudového snímku

## Proč je potřeba

Ayla uchovává naposledy zveřejněné vlastnosti kávovaru. Dotazování i stream DSS
čtou a urychlují změny této cloudové kopie, samy však nepožádají kávovar o nový
snímek statistik. Coffee Link 4.9.6 při otevření statistik odesílá požadavek
`0xe8 0xf0`; kávovar pak nahraje změněné čítače `d5*`/`d7*`, a to i z
pohotovostního režimu. Obnova relace `03 02` znovu zveřejní pouze `d302`.

Integrace používá stejný požadavek u ověřeného profilu Eletta. Čítače, například
využití filtru a objem vody přes vložený filtr, tak nemají záviset na pozdějším
spuštění mobilní aplikace.

## Životní cyklus

- První automatický požadavek se naplánuje 30 sekund po spuštění.
- Po úspěchu se opakuje nejvýše jednou za hodinu.
- Po dokončeném příkazu nápoje se provede znovu, jakmile kávovar nepřipravuje.
- Nápoj připravený přímo na kávovaru vyvolá požadavek osm sekund po přijatém
  přechodu živého monitoru DSS z přípravy do stavu připraveno. Pokud událost
  nedorazí nebo DSS nefunguje, zůstává pravidelná obnova; okamžitou obnovu po
  každém nápoji nelze zaručit.
- Odložený nebo neúspěšný pokus lze zopakovat po pěti minutách.
- Před převzetím relace se kontroluje živé `app_id`. Integrace nepřebírá viditelně
  cizí relaci a neudržuje 140sekundovou smyčku mobilní aplikace na popředí.

Nejde o probuzení ani přípravu nápoje. Požadavek se odloží, když je kávovar
offline, připravuje nápoj nebo právě zpracovává jiný příkaz Home Assistantu.
Nepodporované profily bez ověřeného podpisu dál pouze čtou cloudová data a tento
příkaz určený pro Eletta nedostanou.

Současně může probíhat jen jeden požadavek na statistiky. Další automatický
požadavek se odloží bez přepsání právě probíhající diagnostiky; souběžný ruční
požadavek oznámí, že operace ještě probíhá. Čekání na statistiky nedrží zámek
běžných ovládacích příkazů kávovaru.

## Ověření výsledku

Po odeslání integrace v rámci jediného limitu 45 sekund čeká na změnu snímku
čítačů a poté znovu načte všechny vlastnosti. U Eletty bylo hlášeno doručení za
17–24 sekund; nejde o zaručenou dobu pro každý firmware. Událost beze změny čekání
neukončí předčasně ani neprodlouží celkový limit. Nastavení, například tvrdost
vody, ani verze softwaru se za aktualizaci statistik nepovažují.

Soukromě se porovná otisk hodnot rozpoznaných údržbových a nápojových čítačů
a časů jejich cloudové aktualizace. Otisk, hodnoty, identifikátor kávovaru
ani surový příkaz se do diagnostiky nezapisují.

Stažená diagnostika obsahuje jen počet pokusů a úspěchů, časy, důvod spuštění,
výsledek, informaci o změně snímku a případný stav přesného ACK. Jde o provozní
diagnostiku bez entity a bez historie v databázi. Automatická obnova také nemění
**Stav posledního příkazu**; ten zůstává vyhrazen jen příkazům, které uživatel
nebo automatizace skutečně zadali v Home Assistantu.

- `completed_updated`: pozorovaný snímek se změnil. Neprokazuje čerstvost každého
  jednotlivého čítače.
- `completed_unchanged`: byla přijata relevantní událost DSS, ale výsledný snímek
  zůstal stejný.
- `completed_unverified`: v časovém limitu nebylo možné doložit srovnatelný
  výchozí snímek nebo novou publikaci. Nejde o odmítnutí příkazu ani automaticky
  o zastaralá data; kávovar může posílat pouze změněné hodnoty.

Pozdější události DSS se normálně načtou, aniž by se zpětně přisuzovaly dřívějšímu
požadavku. Počet úspěchů vyjadřuje dokončené cykly požadavku a načtení cloudu,
nikoli zaručenou čerstvost všech čítačů. Důvody spuštění jsou `automatic`,
`post_command`, `beverage_finished` a `manual`.
Toto ověřování se týká požadavku odesílaného kávovaru Eletta. Starší profily
pouze načítají cloud a vyhodnocují porovnání jeho hodnot.

## Ruční diagnostické tlačítko

**Načíst data z cloudu** používá stejný postup a zůstává ve výchozím stavu
deaktivované. Dočasně je povolte pouze při ověřování zastaralých hodnot. Výsledek
`completed_unchanged` je platný, pokud kávovar znovu zveřejní stejné hodnoty;
sám o sobě neznamená chybu.
