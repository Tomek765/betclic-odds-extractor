"""Regression tests derived from Elche–Barcelona Betclic slider DOM."""
import unittest

from core import _extract_dom_from_page
from exhaustive import raw_signature
from parser import parse_market_record


# Minimal, lossless reduction of the real sports-slider-market structure saved in
# tab_run_1787469703_5824_3_SuperSub.html.  The two adjacent rows correspond to
# source records :356 and :357.  The next market reproduces the hard market/group
# boundary visible around :1341/:1342 in the Statystyki snapshot.
REAL_SLIDER_DOM = """
<section>
  <div class="accordion_header">Strzelec</div>
  <sports-slider-market class="block marketElement">
    <div class="marketBox is-groupedMarkets">
      <h3 class="marketBox_headTitle">Liczba celnych strzałów zawodnika (Supersub)</h3>
      <div class="marketBox_body">
        <sports-slider-value class="marketBox_lineSelection">
          <span class="marketBox_label">Lamine Yamal</span>
          <div class="marketBox_slider">
            <div class="forms_slider" style="--sliderMax: 2; --sliderMin: 0; --sliderTextValue: '0.5'; --sliderValue: 0;"></div>
            <button class="btn is-large is-odd">
              <bcdk-bet-button-label class="btn_label is-top"><span>Powyżej</span><span> 0,5</span></bcdk-bet-button-label>
              <bcdk-bet-button-odds-animated class="oddValue">1,08</bcdk-bet-button-odds-animated>
            </button>
          </div>
        </sports-slider-value>
        <sports-slider-value class="marketBox_lineSelection">
          <span class="marketBox_label">Raphinha</span>
          <div class="marketBox_slider">
            <div class="forms_slider" style="--sliderMax: 2; --sliderMin: 0; --sliderTextValue: '0.5'; --sliderValue: 0;"></div>
            <button class="btn is-large is-odd">
              <bcdk-bet-button-label class="btn_label is-top"><span>Powyżej</span><span> 0,5</span></bcdk-bet-button-label>
              <bcdk-bet-button-odds-animated class="oddValue">1,09</bcdk-bet-button-odds-animated>
            </button>
          </div>
        </sports-slider-value>
      </div>
    </div>
  </sports-slider-market>
</section>
<section>
  <div class="accordion_header">Rzuty rożne</div>
  <sports-slider-market class="block marketElement">
    <div class="marketBox is-groupedMarkets">
      <h3 class="marketBox_headTitle">Liczba strzałów zawodnika z pola karnego</h3>
      <div class="marketBox_body">
        <sports-slider-value class="marketBox_lineSelection">
          <span class="marketBox_label">Karim Adeyemi</span>
          <div class="marketBox_slider">
            <div class="forms_slider" style="--sliderMax: 2; --sliderMin: 0; --sliderTextValue: '1.5'; --sliderValue: 0;"></div>
            <button class="btn is-large is-odd">
              <bcdk-bet-button-label class="btn_label is-top"><span>Powyżej</span><span> 1,5</span></bcdk-bet-button-label>
              <bcdk-bet-button-odds-animated class="oddValue">1,48</bcdk-bet-button-odds-animated>
            </button>
          </div>
        </sports-slider-value>
      </div>
    </div>
  </sports-slider-market>
</section>
"""


class SliderPlayerPropAssociation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        page = cls.browser.new_page()
        page.set_content(REAL_SLIDER_DOM)
        cls.rows = _extract_dom_from_page(page, "SuperSub")
        page.close()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_real_adjacent_players_capture_only_their_bounded_context(self):
        self.assertEqual(len(self.rows), 3)
        self.assertEqual(
            [(row["participant_hint"], row["line_hint"], row["selection"], row["odds"]) for row in self.rows[:2]],
            [
                ("Lamine Yamal", "0.5", "Powyżej 0,5", "1.08"),
                ("Raphinha", "0.5", "Powyżej 0,5", "1.09"),
            ],
        )
        self.assertNotEqual(self.rows[0]["market_instance_id"], self.rows[1]["market_instance_id"])

    def test_parser_preserves_player_line_selection_and_odds(self):
        parsed = []
        for index, raw in enumerate(self.rows[:2], start=356):
            row, unresolved = parse_market_record(
                category=raw["category"], market_title=raw["market"],
                raw_selection=raw["selection"], odds_str=raw["odds"], raw_text=raw["raw"],
                section_title=raw["section_title"], ancestor_title=raw["ancestor_title"],
                home_team="Elche", away_team="Barcelona", container_id=raw["container_id"],
                period_hint=raw["period_hint"], line_hint=raw["line_hint"],
                participant_hint=raw["participant_hint"], main_tab=raw["active_tab"],
                market_instance_id=raw["market_instance_id"],
                raw_record_id=f"run_1787469703_5824:{index}",
            )
            self.assertIsNone(unresolved)
            parsed.append(row)

        self.assertEqual(
            [(row["PARTICIPANT"], row["LINE"], row["SELECTION"], row["ODDS"]) for row in parsed],
            [
                ("Lamine Yamal", "0.5", "OVER", "1.08"),
                ("Raphinha", "0.5", "OVER", "1.09"),
            ],
        )

    def test_first_player_of_next_market_cannot_inherit_previous_scope(self):
        previous, next_market = self.rows[1], self.rows[2]
        self.assertEqual(previous["participant_hint"], "Raphinha")
        self.assertEqual(next_market["participant_hint"], "Karim Adeyemi")
        self.assertEqual(next_market["line_hint"], "1.5")
        self.assertNotEqual(previous["market"], next_market["market"])
        self.assertNotEqual(previous["market_instance_id"], next_market["market_instance_id"])

    def test_virtualized_union_identity_includes_bounded_participant(self):
        base = {
            "market_instance_id": "same-virtual-row", "market": "Player shots",
            "selection": "Powyżej 0,5", "odds": "1.50", "line_hint": "0.5",
        }
        self.assertNotEqual(
            raw_signature({**base, "participant_hint": "Lamine Yamal"}),
            raw_signature({**base, "participant_hint": "Raphinha"}),
        )


if __name__ == "__main__":
    unittest.main()
