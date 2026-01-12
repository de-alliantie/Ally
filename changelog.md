# Changelog

Alle belangrijke wijzigingen aan de app (behalve werkzaamheden aan de infra) worden bijgehouden in deze file.

### [0.2.11]

- Logo en iconen aangepast conform huisstijl

### [0.2.10]

- Verbeterde huisstijl toegepast, zijbalk nu blauw.

### [0.2.9]

- Upgrade LLM naar gpt-4o voor kostenbesparing en verbeterde antwoorden.

### [0.2.8]

- Fix: OpenSSH updated (security).

### [0.2.7]

- Fix: warrig document van dagelijkse rapportage gefixt.

### [0.2.6]

###### Nieuwe features

- Helpjuice API geïmplementeerd

###### Gewijzigd

- In de dagelijkse rapportage staan alle vermelde bronnen, niet alleen van het laatste antwoord in een gesprek.
- In de app (live) worden ook de eerdere bronnen vermeld.
- Sommige gesprekken werden niet gerapporteerd vanwege issue met "Start nieuwe chat" knop. Is nu opgelost.
- In de rapportage staat ook hoeveelste "sessie" het was (wanneer je de pagina refresht start een nieuwe sessie). Let op: hiermee worden niet het aantal gebruikers geteld.

### [0.2.5]

###### Nieuwe features

- Datum van laatste kennisbank update nu te zien onder `Over Ally`.

###### Gewijzigd

- Senior medewerkers krijgen nu dagelijkse notificatie met de vragen die aan Ally gesteld zijn.

### [0.2.4]

- Fix bug

### [0.2.3]

###### Nieuwe features

- Opslaan van chats t.b.v. feedback-cyclus


### [0.2.2]

###### Gewijzigd

- Ally

### [0.2.1]

###### Gewijzigd

- Fix: huisstijl werkend

### [0.2.0]

###### Nieuwe features

- Klikbare links naar de artikelen.

### [0.1.0]

Eerste release van app

###### Nieuwe features

- Mogelijkheid om feedback te kunnen geven
- Semantisch zoeken (zonder chat) in de kennisbank van de Klantenservice

###### Gewijzigd

- Design op basis van huisstijl
- Refactoring code
- Betere performance qua belasting infra

### [0.0.1] - Unreleased (demo)

Demo

###### Features

- Chatten, met chatGPT 3.5-turbo via Azure OpenAI, met de kennisbank van de Klantenservice
