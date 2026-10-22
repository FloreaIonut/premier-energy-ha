# Premier Energy pentru Home Assistant

Integrare custom (neoficială) care citește facturile de gaz din portalul clienților `my.premierenergy.ro`.
**Neoficial: nu este afiliată cu Premier Energy.** Folosește portalul pentru clienți; dacă portalul se schimbă, integrarea se poate strica.

*English: unofficial Home Assistant custom integration that reads gas invoices from the Premier Energy (Romania) customer portal. Not affiliated with Premier Energy. Install via HACS (custom repository) or by copying `custom_components/premier_energy`, then add the integration with your my.premierenergy.ro email and password. Polls every 6 hours. Gas and invoices only; paid/unpaid status is not exposed by the portal. Debug: enable logs for `custom_components.premier_energy`.*

## Ce face
Pentru fiecare punct de consum de gaz (PoD care începe cu `DGS`) creează un dispozitiv cu 5 senzori:

- **Ultima factură**: suma în lei (negativ = credit). Atribute: `pod`, `adresa`, `facturi` (ultimele 12).
- **Scadență**: data scadenței ultimei facturi.
- **Data emiterii**: data ultimei facturi.
- **Număr factură**: numărul ultimei facturi.
- **Număr facturi**: câte facturi returnează portalul.

Datele se actualizează la 6 ore.

## Instalare

### Varianta 1: HACS (repository custom)
1. HACS → meniul cu 3 puncte → **Custom repositories**.
2. Adaugă `https://github.com/FloreaIonut/premier-energy-ha`, categoria **Integration**.
3. Caută „Premier Energy”, **Download**, apoi repornește Home Assistant.

### Varianta 2: manual
1. Copiază folderul `custom_components/premier_energy` în `/config/custom_components/`.
2. Repornește Home Assistant.

## Configurare
Setări → Dispozitive și servicii → Adaugă integrare → **Premier Energy**. Introdu emailul și parola contului de pe my.premierenergy.ro. Datele de acces rămân doar în Home Assistant. Dacă schimbi parola, HA cere reautentificarea.

## Limitări
- Neoficial, neafiliat; se bazează pe portalul clienți, care se poate schimba oricând.
- Doar gaz și facturi (fără index, consum sau PDF).
- Starea „plătit / neplătit" nu este disponibilă în API.

## Depanare
Adaugă în `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.premier_energy: debug
```
Logurile nu conțin parole sau token-uri. Nu posta date personale (PoD, număr factură, adresă) în issue-uri.

## Test offline
`python3 tests/test_offline.py` (date sintetice, fără login).

## Licență
MIT
