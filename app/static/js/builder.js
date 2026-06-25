// Pure UI convenience — every field shown here is still validated and
// re-collected on the server in validate_offer_params(); this script just
// avoids showing all three offer types' fields at once.
function showOfferFields(selectedType) {
    document.querySelectorAll(".offer-fields").forEach(function (el) {
        el.style.display = "none";
        el.querySelectorAll("input").forEach(function (input) {
            input.disabled = true;
        });
    });
    if (!selectedType) return;
    var target = document.getElementById("fields-" + selectedType);
    if (target) {
        target.style.display = "block";
        target.querySelectorAll("input").forEach(function (input) {
            input.disabled = false;
        });
    }
}
