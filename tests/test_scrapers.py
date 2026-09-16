import json
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from src.scraper import (WahlinArenaScraper, HeimstadenArenaScraper, WahlinRentalScraper,
                         WallfastRentalScraper, ShapeChanged, FetchError)


ARENA_OBJECT = {
    "Guid": "8002adfd-b729-4a9d-ac4c-b0fd0144ea15", "Id": "502-204", "Adress1": "Södergatan 1 F",
    "Adress2": "195 34", "Adress3": "MÄRSTA", "AvailableDate": "2026-09-01T00:00:00",
    "Cost": 10797, "TotalCost": 10797, "FlatNumber": "1001", "Floor": 0,
    "MoveInDate": "2026-10-01T00:00:00", "NoOfRooms": 2, "AreaName": "Märsta", "Size": 63,
    "DetailsUrl": "/ledigt/detalj/id/502-204", "ShowDateStart": "2026-09-16T00:00:00",
    "ShowDateEnd": "2026-09-19T23:59:00", "StateId": "PUBLISHED", "ShowRandomSort": True,
}


def fake_response(*, text="", json_data=None, status=200):
    def _json():
        if json_data is None:
            raise ValueError("no json")
        return json_data
    return SimpleNamespace(text=text, status_code=status, json=_json)


class TestWahlinArena:
    def test_parses_plain_list(self):
        listings = WahlinArenaScraper.parse_objects([ARENA_OBJECT])
        assert len(listings) == 1
        l = listings[0]
        assert l.object_id == "502-204"
        assert l.key == "wahlin:502-204:2026-09-16"
        assert l.url == "https://minasidor.wahlinfastigheter.se/ledigt/detalj/id/502-204"
        assert l.rent_cost == "10 797 kr"
        assert l.size == "63 kvm"
        assert l.number_of_rooms == "2 rok"
        assert l.area == "Märsta"
        assert "Södergatan 1 F" in l.street
        assert l.published_until == "2026-09-19 23:59"
        assert l.lottery is True
        assert l.move_in == "2026-10-01"

    def test_parses_wrapped_data_string(self):
        wrapped = {"status": "success", "data": json.dumps([ARENA_OBJECT])}
        assert len(WahlinArenaScraper.parse_objects(wrapped)) == 1

    def test_republication_gets_new_key(self):
        again = dict(ARENA_OBJECT, ShowDateStart="2026-10-02T00:00:00")
        k1 = WahlinArenaScraper.parse_objects([ARENA_OBJECT])[0].key
        k2 = WahlinArenaScraper.parse_objects([again])[0].key
        assert k1 != k2

    def test_empty_list_is_ok(self):
        assert WahlinArenaScraper.parse_objects([]) == []

    def test_shape_change_detected(self):
        with pytest.raises(ShapeChanged):
            WahlinArenaScraper.parse_objects({"unexpected": 1})
        with pytest.raises(ShapeChanged):
            WahlinArenaScraper.parse_objects([{"Foo": "bar"}])

    def test_fetch_reports_html_login_page_as_shape_change(self, monkeypatch):
        s = WahlinArenaScraper()
        monkeypatch.setattr(s, "_get", lambda url: fake_response(text="<html>login</html>"))
        r = s.fetch()
        assert not r.ok and r.shape_changed and r.listings == []

    def test_fetch_reports_http_error(self, monkeypatch):
        s = WahlinArenaScraper()

        def boom(url):
            raise FetchError("HTTP 503", status_code=503)
        monkeypatch.setattr(s, "_get", boom)
        r = s.fetch()
        assert not r.ok and r.status_code == 503 and not r.shape_changed

    def test_url_has_cache_buster(self):
        assert "timestamp=" in WahlinArenaScraper().url()


WAHLIN_HTML = """
<html><head><link href="/wp-content/themes/wahlinfastigheter/style.css"></head><body>
<article class="group/item">
  <a href="/hyr-av-oss/omrade/marsta/">Märsta</a>
  <h2>Södergatan 2 L</h2>
  <dl><dt>Antal rum</dt><dd>1 rok</dd><dt>Hyra (kr/mån)</dt><dd>8 372 kr</dd><dt>Area</dt><dd>42 kvm</dd></dl>
  <a href="https://wahlinfastigheter.se/lediga-objekt/sodergatan-2-l-506-312/">Visa</a>
</article>
<article class="group/item">
  <a href="/hyr-av-oss/omrade/knivsta/">Knivsta</a>
  <h2>Faktorns gata 13</h2>
  <dl><dt>Antal rum</dt><dd>2 rok</dd></dl>
  <a href="https://wahlinfastigheter.se/lediga-objekt/faktorns-gata-13-520-3-1001-2/">Visa</a>
</article>
</body></html>
"""


class TestWahlinWeb:
    def test_parses_articles_and_object_ids(self):
        listings = WahlinRentalScraper.parse_html(BeautifulSoup(WAHLIN_HTML, "html.parser"))
        assert [l.object_id for l in listings] == ["506-312", "520-3-1001"]
        assert listings[0].rent_cost == "8 372 kr"
        assert listings[0].key == listings[0].url

    @pytest.mark.parametrize("url,expected", [
        ("https://wahlinfastigheter.se/lediga-objekt/rasundavagen-31-356-124/", "356-124"),
        ("https://wahlinfastigheter.se/lediga-objekt/klyvargatan-14-520-4-1210-3/", "520-4-1210"),
        ("https://wahlinfastigheter.se/lediga-objekt/grafikvagen-9-johanneshov/", None),
    ])
    def test_object_id_regex(self, url, expected):
        m = WahlinRentalScraper.OBJECT_ID_RE.search(url)
        assert (m.group(1) if m else None) == expected

    def test_empty_page_with_theme_marker_is_ok(self, monkeypatch):
        s = WahlinRentalScraper()
        html = '<html><link href="/wp-content/themes/wahlinfastigheter/x.css"><body>Inga lediga</body></html>'
        monkeypatch.setattr(s, "_get", lambda url: fake_response(text=html))
        r = s.fetch()
        assert r.ok and r.listings == []

    def test_unrecognised_page_is_shape_change(self, monkeypatch):
        s = WahlinRentalScraper()
        monkeypatch.setattr(s, "_get", lambda url: fake_response(text="<html>Access denied</html>"))
        r = s.fetch()
        assert not r.ok and r.shape_changed


WALLFAST_HTML = """
<html><head><title>LEDIGA OBJEKT - WALLFAST</title></head><body>
<ul class="sv-channel">
<li class="sv-channel-item"><div class="men-startpage--newslist-item">
  <div class="men-startpage--newslist-item--heading">
    <a href="/lediga-objekt/annonser/2026-09-16-lagenhet-2-rok-54-kvm-solna">Lägenhet 2 rok 54 kvm Solna</a>
  </div></div></li>
</ul></body></html>
"""


class TestWallfast:
    def test_parses_items(self):
        listings = WallfastRentalScraper.parse_html(BeautifulSoup(WALLFAST_HTML, "html.parser"))
        assert len(listings) == 1
        l = listings[0]
        assert l.url == "https://wallfast.com/lediga-objekt/annonser/2026-09-16-lagenhet-2-rok-54-kvm-solna"
        assert l.size == "54 kvm"
        assert l.area == "Solna"
        assert l.lottery is True

    def test_empty_listing_page_is_ok(self, monkeypatch):
        s = WallfastRentalScraper()
        html = "<html><head><title>LEDIGA OBJEKT - WALLFAST</title></head><body>Inga annonser</body></html>"
        monkeypatch.setattr(s, "_get", lambda url: fake_response(text=html))
        r = s.fetch()
        assert r.ok and r.listings == []

    def test_unrecognised_page_is_shape_change(self, monkeypatch):
        s = WallfastRentalScraper()
        monkeypatch.setattr(s, "_get", lambda url: fake_response(text="<html><title>Oops</title></html>"))
        r = s.fetch()
        assert not r.ok and r.shape_changed


class TestHeimstadenArena:
    def test_parses_with_own_prefix_and_base_url(self):
        obj = dict(ARENA_OBJECT, Id="6913112-1202", Adress1="Roslagsgatan 38 B ", AreaName="Stockholm - Vasastaden",
                   DetailsUrl="/ledigt/detalj/id/6913112-1202", ShowDateEnd=None, ShowRandomSort=False)
        l = HeimstadenArenaScraper.parse_objects([obj])[0]
        assert l.key == "heimstaden:6913112-1202:2026-09-16"
        assert l.url == "https://mitt.heimstaden.com/ledigt/detalj/id/6913112-1202"
        assert l.area == "Vasastaden"                    # city prefix stripped for the notification title
        assert l.street.startswith("Roslagsgatan 38 B")  # trailing space trimmed
        assert l.published_until is None and l.lottery is False

    def test_wahlin_keys_unchanged(self):
        assert WahlinArenaScraper.parse_objects([ARENA_OBJECT])[0].key.startswith("wahlin:")

    def test_url_points_at_heimstaden(self):
        assert HeimstadenArenaScraper().url().startswith("https://mitt.heimstaden.com/rentalobject/Listapartment/published")
