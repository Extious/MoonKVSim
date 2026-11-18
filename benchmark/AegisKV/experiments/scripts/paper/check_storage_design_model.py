#!/usr/bin/env python3
"""Executable checks of paper examples; not a production cache/controller test."""
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass(frozen=True)
class Group:
    name: str
    size: float
    key: float
    eligible: bool = True


def preview(rent, residents, incoming, free):
    """Read-only rental screening, preceding joint plan valuation/reservation."""
    trial=rent;victims=[];released=free
    for x in sorted((x for x in residents if x.eligible),key=lambda x:(x.key,x.name)):
        if released>=incoming.size:break
        if incoming.key<=max(trial,x.key):return None
        trial=max(trial,x.key);victims.append(x.name);released+=x.size
    return (trial,victims) if released>=incoming.size else None


def main():
    checks=[]
    def check(name,condition):
        assert condition,name
        checks.append(name)
    residents=[Group('y',1,2),Group('z',1,5),Group('leased',1,1,False)]
    incoming=Group('x',1,6)
    check('Figure rental: y is the safe victim',preview(0,residents,incoming,0)==(2,['y']))
    check('All physical groups age, including leased',
          [x.size*max(0,x.key-2) for x in residents]==[0,3,0])
    check('Incoming trial credit pays the same trial rent',incoming.size*(incoming.key-2)==4)
    check('Free space does not raise rent',preview(0,residents,incoming,1)==(0,[]))
    check('Equal expiration keeps resident',preview(0,residents,Group('x',1,2),0) is None)
    check('Empty safe set refuses admission',preview(0,[residents[-1]],incoming,0) is None)
    check('Already expired keys cannot reduce rent',preview(3,residents,incoming,0)==(3,['y']))
    check('Multiple victims advance one monotone trial',preview(0,residents,Group('x',2,6),0)==(5,['y','z']))
    check('Insufficient eligible bytes rejects whole trial',preview(0,residents,Group('x',3,6),0) is None)
    check('Rejected preview leaves resident keys untouched',[x.key for x in residents]==[2,5,1])
    # Settle proportional owner shares before renewing the event's owner only.
    old={'a':6.,'b':4.};paid=5.;remaining={k:v*(1-paid/sum(old.values())) for k,v in old.items()}
    remaining['a']=8.
    check('Shared renewal does not refund another owner',remaining=={'a':8.,'b':2.})
    # A complete two-branch common-fault objective is not an additive local score.
    before=max(10,10);one=max(2,10);both=max(2,2)
    check('One improved branch need not advance the join',before-one==0)
    check('Two improvements jointly help without adding local gains',before-both==8 and (10-2)*2==16)
    # Publication and physical allocation are distinct. Normalized illustrative events.
    dram_used=3;cap=3;pending_ssd=1;frontier=128;copied_layer_frontiers=[192,128,192]
    check('Pending storage does not free DRAM or advance frontier',dram_used==cap and frontier==min(copied_layer_frontiers))
    valid_ssd=True;readers=1
    can_free=valid_ssd and readers==0
    check('Committed replacement still waits for old readers',not can_free)
    readers=0;can_free=valid_ssd and readers==0
    check('Only drained committed replacement releases bytes',can_free)
    record={'evidence':'reference arithmetic/specification checks, not a deployed controller',
            'count':len(checks),'checks':checks,
            'not_tested':['distributed races','backend durability','actual engine hooks',
                          'controller runtime overhead','end-to-end WCT or serving performance']}
    out=Path(__file__).resolve().parents[3]/'exports/system-design-dram-ssd-20260920/data'
    out.mkdir(parents=True,exist_ok=True);(out/'SPEC_CHECKS.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()
