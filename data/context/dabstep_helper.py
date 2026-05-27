"""
Canonical DABStep match helpers.

Encodes the verified-ground-truth wildcard semantics from docs/domain_knowledge.md.
Use these rather than writing per-task match logic — empty-list-as-wildcard and
is_credit-is-bool are the two most common bug families and both are handled here.
"""
import math as _math


def list_match(rule_val, txn_val):
    """Rule list-field matches iff null OR empty list OR contains txn_val."""
    if rule_val is None:
        return True
    if isinstance(rule_val, list):
        return len(rule_val) == 0 or txn_val in rule_val
    return rule_val == txn_val


def scal_match(rule_val, txn_val):
    """Rule scalar-field matches iff null/NaN OR equals txn_val."""
    if rule_val is None:
        return True
    if isinstance(rule_val, float) and _math.isnan(rule_val):
        return True
    return rule_val == txn_val


def attr_matches_wildcard(rule_attr, query_val):
    """For attribute-filter questions: include wildcard rules.
    True iff rule's field is null/empty OR matches query_val."""
    if rule_attr is None:
        return True
    if isinstance(rule_attr, list):
        return len(rule_attr) == 0 or query_val in rule_attr
    return rule_attr == query_val


def rule_applies(rule, txn, merchant=None):
    """Canonical per-txn rule-applicability predicate.

    Args:
        rule: dict from fees.json (one rule).
        txn: dict-like row from payments.csv (one transaction).
        merchant: optional merchant_data row (provides capture_delay_bucket /
                  account_type / mcc).

    Returns True iff the rule applies to this transaction under DABStep's
    wildcard semantics.
    """
    if not scal_match(rule.get("card_scheme"), txn.get("card_scheme")):
        return False
    if not scal_match(rule.get("is_credit"), bool(txn.get("is_credit"))):
        return False
    if merchant is not None:
        if not scal_match(rule.get("capture_delay"), merchant.get("capture_delay_bucket")):
            return False
        if not list_match(rule.get("account_type"), merchant.get("account_type")):
            return False
        if not list_match(rule.get("merchant_category_code"), merchant.get("mcc")):
            return False
    if not list_match(rule.get("aci"), txn.get("aci")):
        return False
    if not scal_match(rule.get("monthly_volume"), txn.get("monthly_volume_bucket")):
        return False
    if not scal_match(rule.get("monthly_fraud_level"), txn.get("monthly_fraud_level_bucket")):
        return False
    rule_intra = rule.get("intracountry")
    if rule_intra is not None and not (isinstance(rule_intra, float) and _math.isnan(rule_intra)):
        txn_intra = bool(txn.get("issuer_country") == txn.get("acquirer_country"))
        if bool(rule_intra) != txn_intra:
            return False
    return True


def fee_for_rule(rule, eur_amount):
    """Manual §5 fee formula: fee = fixed_amount + rate * tx_value / 10000."""
    return float(rule.get("fixed_amount", 0.0)) + float(rule.get("rate", 0.0)) * float(eur_amount) / 10000.0
