from src.demo.api_router import APIRouter


def test_owner_best_selling_question_has_useful_answer_in_chat():
    result = APIRouter().process_request("what is the best selling cars you have", [])
    assert "sales ranking" in result["response"].lower()
    assert "Rogue" in result["response"] and "Atlas" in result["response"]
    assert "passengers" in result["response"].lower()
    assert result["vehicle_cards"]


def test_family_followup_uses_capacity_and_explains_tradeoffs():
    history = [{"role": "user", "content": "Help me choose an SUV"}]
    result = APIRouter().process_request("I need 7 seats", history)
    assert "Atlas" in result["response"] and "XC90" in result["response"]
    assert all(card["seats_max"] >= 7 for card in result["vehicle_cards"])


def test_comparison_is_answered_without_asking_customer_to_leave():
    result = APIRouter().process_request("compare Rogue and Atlas", [])
    assert "five" in result["response"].lower() and "three rows" in result["response"].lower()
    assert len(result["vehicle_cards"]) == 2
    assert result["brand"] == "all"


def test_unknown_dealer_stock_and_sales_are_never_invented():
    result = APIRouter().process_request("Which sells most and how many do you have?", [])
    assert result.get("dealer_sales_rank") is None
    assert result.get("stock_verified") is False
    assert all(card["data_status"] == "model_guide_not_stock" for card in result["vehicle_cards"])


def test_model_choice_after_comparison_uses_its_own_showroom():
    result = APIRouter().process_request(
        "I want the Atlas", [{"role": "user", "content": "compare Rogue and Atlas"}], location_id="nissan"
    )
    assert result["vehicle_cards"][0]["id"] == "atlas"
    assert result["location_id"] == "volkswagen"
    assert result["brand"] == "volkswagen"
    assert any("jackingramvolkswagen.com" in link["url"] for link in result["links"])


def test_explorer_question_switches_from_family_shopping_context():
    result = APIRouter().process_request(
        "Tell me about the Porsche 911 in 3D", [{"role": "user", "content": "I need 7 seats"}]
    )
    assert [card["id"] for card in result["vehicle_cards"]] == ["911"]
    assert "For 7 passengers" not in result["response"]
    assert "show rear wheels" in result["response"]
