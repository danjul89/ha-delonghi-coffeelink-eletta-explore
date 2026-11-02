# De'Longhi Coffee Link – Eletta Explore pro Home Assistant

Neoficiální samostatná cloudová integrace pro kávovary De'Longhi Eletta Explore
připojené přes Coffee Link a platformu Ayla IoT.

## Stav projektu

| Položka | Stav |
|---|---|
| Aktuální vydání | 1.3.1 – automatické kontroly, veřejné CI a živé ověření v cílovém HA prošly |
| Fyzické ověření příkazů | 1.3.0-beta.6 – probuzení, Cold Brew Start/Stop a pohotovostní režim na ověřeném kávovaru Eletta prošly |
| Ověřený kávovar | Eletta Explore ECAM450.65.G (`DL-striker-cb`, oblast EU) |
| Home Assistant | 2026.8.2 nebo novější |
| Jazyky | čeština a angličtina |
| Automatické testy | 402 izolovaných testů se 100% pokrytím + 4 testy ve skutečném HA pro každou z verzí 2026.8.2 a 2026.10.4 |
| Distribuce | vlastní repozitář HACS nebo ruční instalace z vydání na GitHubu; zařazení do výchozího katalogu se posuzuje |

Profil PrimaDonna Soul zůstává v kódu pro zkoušky kompatibility, neprošel však
stejným fyzickým ověřením a je označen jako experimentální.

## Co integrace poskytuje

- stav kávovaru, připojení ke cloudu a údržbové stavy;
- téměř okamžité cloudové aktualizace DSS a u vlastností s podporou ACK přesná
  potvrzení datového bodu; příkazový kanál ověřeného modelu Eletta podporu ACK
  nemá, proto se stejně jako v Coffee Link potvrzuje změnou stavu kávovaru;
- automatický návrat k 30sekundovému dotazování při výpadku streamu;
- bezpečné vyžádání nového snímku přímo z kávovaru po spuštění integrace,
  jednou za hodinu a po dokončeném příkazu nápoje; při přípravě, výpadku nebo
  cizí relaci se požadavek odloží;
- počitadla nápojů, vody, filtru, odvápnění a zásobníku sedliny;
- souhrnné statistiky se stejným významem pro Eletta/Striker a starší větev
  PrimaDonna Soul; u neznámého modelu se význam interních polí neodhaduje;
- podrobná počitadla jednotlivých receptů zůstávají dostupná, ale pro nově
  registrované entity jsou ve výchozím stavu vypnutá;
- dynamická tlačítka nápojů naučená z oficiální aplikace Coffee Link;
- automatické načtení přidaného kávovaru a odstranění záznamů odebraného
  kávovaru;
- zapnutí, pohotovostní režim, synchronizaci dat a bezpečné zastavení;
- rozpoznání kolize relace Coffee Link a stav posledního příkazu Home Assistantu;
- automatické obnovení krátkodobé cloudové relace bez výzvy k zadání hesla;
- kontrolu připravenosti, nádržky na vodu a zásobníku sedliny před přípravou;
- ověření kontrolního součtu, typu příkazu, nápoje a podpisu zařízení;
- diagnostiku bez přihlašovacích údajů, identifikátorů zařízení a surových příkazů;
- přeložené položky Opravy, které upozorní na poškozený uložený příkaz a po
  opětovném naučení samy zmizí.

Entita **Relace Coffee Link** zobrazuje, zda je výhradní příkazová relace
**Volná**, **Aktivní** pod sdíleným identifikátorem Coffee Link, nebo ji používá
**Jiná aplikace**. Sdílený identifikátor nerozliší tuto integraci od oficiální
aplikace, proto je stav záměrně neutrální. **Stav posledního příkazu** sleduje
jen příkazy odeslané z Home Assistantu; provoz oficiální aplikace se do něj
nezapisuje.

Výchozí stav entity použije Home Assistant jen při jejím prvním zaregistrování.
Aktualizace proto nevypne podrobná počitadla, která už má stávající instalace
zapnutá; lze je spravovat jednotlivě na stránce **Entity** daného zařízení.

## Zásobník na sedlinu a reset čítače

**Naplnění zásobníku sedliny** přebírá vypočítané procento z cloudu výrobce;
nejde o přímé fyzické měření hladiny. **Zásobník na sedlinu** zobrazuje aktuální
alarm plného nebo chybějícího zásobníku a je rozhodující pro upozornění,
bezpečnostní kontroly a automatizace. Obě hodnoty se proto mohou dočasně lišit.

Čítač se spolehlivě vynuluje pouze při probuzeném kávovaru. Počkejte na stav
**Připraveno**, vyjměte celou odkapávací misku se zásobníkem na několik sekund,
zásobník vyprázdněte a obě části vraťte. Neprovádějte to během přípravy nápoje
nebo proplachování. Vyprázdnění v pohotovostním režimu nemusí kávovar zaznamenat.
Poté vyčkejte na cloudovou aktualizaci; pro diagnostiku lze dočasně povolit
deaktivovanou entitu **Načíst data z cloudu**. Viz
[oficiální pokyny De'Longhi](https://www.delonghi.com/en-us/faqs/The-grounds-container-light-is-on-but-my-ground-container-is-not-full./a/16760).

## Instalace

[![Otevřít tento repozitář v HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kasiom&repository=ha-delonghi-coffeelink-eletta-explore&category=integration)

Dokud integrace nebude součástí výchozího katalogu HACS, přidejte ji jednou jako
vlastní repozitář:

[Žádost o zařazení](https://github.com/hacs/default/pull/10136) je nyní ve frontě
na kontrolu HACS.

1. v HACS otevřete **Vlastní repozitáře**;
2. přidejte
   `https://github.com/kasiom/ha-delonghi-coffeelink-eletta-explore`
   jako **Integraci**;
3. nainstalujte **De'Longhi Coffee Link – Eletta Explore** a restartujte Home
   Assistant;
4. v **Nastavení → Zařízení a služby → Přidat integraci** vyhledejte
   **De'Longhi Coffee Link – Eletta Explore**.

Při ruční instalaci stáhněte nejnovější vydání, zkopírujte celou složku
`custom_components/ha_delonghi_coffeelink_eletta_explore` do
`/config/custom_components/` a restartujte Home Assistant. Nemíchejte soubory z
různých vydání. Podrobnosti jsou v [návodu k instalaci](INSTALLATION.md).

## Naučení nápoje

Připravte požadovaný nápoj jednou v oficiální aplikaci Coffee Link, zatímco
Home Assistant běží. Integrace příkaz zkontroluje, bezpečně uloží a vytvoří
odpovídající tlačítko. Přes DSS se nové tlačítko zpravidla objeví ihned; při
náhradním dotazování nejpozději přibližně do 30 sekund. Opakované
naučení stejného receptu nahradí jeho starší příkaz.

Tlačítko **Zastavit přípravu nápoje** je dostupné jen tehdy, když integrace zná
právě připravovaný nápoj i jeho platný příkaz pro zastavení.

## Podpora projektu

Pokud je pro vás tento nezávislý projekt užitečný, můžete jej dobrovolně podpořit
na společné [stránce podpory](https://kasiom.github.io/support/). Podpora nemá
vliv na přístup k vydáním, řešení hlášení, priority funkcí ani licenci MIT.

## Bezpečnost

Vzdálený příkaz může spustit výdej horké vody, kávy, mléka nebo páry. Vždy
zkontrolujte správný šálek, připojené příslušenství a prostor kolem kávovaru.
Integraci nepoužívejte k bezobslužnému vzdálenému výdeji.

Další informace: [použití a bezpečnost](USAGE.md),
[obnova cloudového snímku](CLOUD_SNAPSHOT_REFRESH_CS.md),
[kompatibilita](COMPATIBILITY.md), [řešení potíží](TROUBLESHOOTING.md) a
[ochrana soukromí](PRIVACY.md).
