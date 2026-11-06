"""Fast standalone regression tests for claim expiry and content fingerprints."""
import datetime
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import rules

def test_expired_claim():
    yesterday=(datetime.date.today()-datetime.timedelta(days=1)).isoformat()
    tomorrow=(datetime.date.today()+datetime.timedelta(days=1)).isoformat()
    claim='Our offer is valid for selected members'
    issues, links=rules.check_claims(claim,[{'claim':claim,'expires_on':yesterday}])
    assert any(i['rule_code']=='CLAIM_EXPIRED' and i['severity']=='high' for i in issues)
    assert claim not in links
    issues, links=rules.check_claims(claim,[{'claim':claim,'expires_on':tomorrow}])
    assert not any(i['rule_code']=='CLAIM_EXPIRED' for i in issues)
    assert claim in links

if __name__=='__main__':
    test_expired_claim()
    print('PASS: expired claims rejected; current claims allowed')
