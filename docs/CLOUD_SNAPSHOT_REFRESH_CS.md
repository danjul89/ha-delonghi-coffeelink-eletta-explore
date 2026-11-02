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
- Nápoj připravený přímo na kávovaru vyvolá požadavek několik sekund poté, co
  živý monitor přejde z přípravy do stavu připraveno.
- Odložený nebo neúspěšný pokus lze zopakovat po pěti minutách.
- Před převzetím relace se kontroluje živé `app_id`. Integrace nepřebírá viditelně
  cizí relaci a neudržuje 140sekundovou smyčku mobilní aplikace na popředí.

Nejde o probuzení ani přípravu nápoje. Požadavek se odloží, když je kávovar
offline, připravuje nápoj nebo právě zpracovává jiný příkaz Home Assistantu.
Nepodporované profily bez ověřeného podpisu dál pouze čtou cloudová data a tento
příkaz určený pro Eletta nedostanou.

## Ověření výsledku

Po odeslání integrace čeká nejvýše deset sekund na událost DSS vlastnosti `d5*`
nebo `d7*` a poté znovu načte všechny vlastnosti. Soukromě porovná otisk hodnot
čítačů a časů jejich cloudové aktualizace. Otisk, hodnoty, identifikátor kávovaru
ani surový příkaz se do diagnostiky nezapisují.

Stažená diagnostika obsahuje jen počet pokusů a úspěchů, časy, důvod spuštění,
výsledek, informaci o změně snímku a případný stav přesného ACK. Jde o provozní
diagnostiku bez entity a bez historie v databázi. Automatická obnova také nemění
**Stav posledního příkazu**; ten zůstává vyhrazen jen příkazům, které uživatel
nebo automatizace skutečně zadali v Home Assistantu.

## Ruční diagnostické tlačítko

**Načíst data z cloudu** používá stejný postup a zůstává ve výchozím stavu
deaktivované. Dočasně je povolte pouze při ověřování zastaralých hodnot. Výsledek
`completed_unchanged` je platný, pokud kávovar znovu zveřejní stejné hodnoty;
sám o sobě neznamená chybu.
