"""Normalize free-form corpus metadata into stable retrieval fields.

This is deliberately conservative: it adds IDs from text already present in
the artifact and never invents transcript evidence.
"""
from __future__ import annotations
from typing import Any

SITUATIONS={
 "unrequited_love":["एकतरफा प्रेम","अप्रत्युत्तरित प्रेम","प्रेम का प्रत्युत्तर न मिलना","सामने वाला प्रेम न करे","प्रेम को न समझना","unrequited love","one sided love"],
 "attachment_in_love":["प्रेम में आसक्ति","प्रेम में अपेक्षा","emotional attachment"],
 "relationship_conflict":["रिश्ते में विवाद","relationship conflict"],
 "grief_separation":["वियोग","बिछड़ना","separation","grief"],
 "anxiety_fear":["चिंता","भय","घबराहट","anxiety","fear"],
 "anger":["क्रोध","गुस्सा","anger"],"jealousy":["ईर्ष्या","जलन","jealousy"],
 "temptation":["वासना","लालच","प्रलोभन","temptation"],
 "devotional_practice":["भक्ति","साधना","नाम जप","devotional practice"],
}
INTENTS={
 "seek_guidance":["क्या करना चाहिए","क्या करें","मार्गदर्शन","what should i do","seek guidance"],
 "understand_teaching":["अर्थ क्या है","समझना","what does it mean","understand"],
 "seek_practice":["कैसे करें","अभ्यास","how to practice"],
 "seek_reassurance":["आश्वासन","सांत्वना","reassurance"],
}
RECIPROCITY={
 "not_reciprocated":["प्रेम नहीं करता","प्यार नहीं करती","প্রेम का प्रत्युत्तर नहीं","not reciprocated","does not love back"],
 "uncertain":["पता नहीं","शायद","uncertain"],"reciprocated":["परस्पर प्रेम","mutual love","loves back"],
}
RELATIONSHIPS={"romantic":["लड़की","लड़का","प्रेमी","प्रेमिका","पति","पत्नी","romantic","partner","girlfriend","boyfriend"],
"family":["माता","पिता","भाई","बहन","परिवार","family"],"friendship":["दोस्त","मित्र","friend","friendship"],
"devotional":["गुरु","भगवान","भक्ति","devotional"]}

def _list(value:Any,limit:int=30)->list[str]:
 if not isinstance(value,list): return []
 out=[];seen=set()
 for x in value:
  if not isinstance(x,str): continue
  x=" ".join(x.split()).strip()
  if x and x.casefold() not in seen: seen.add(x.casefold());out.append(x)
  if len(out)>=limit: break
 return out

def _match(values:Any,vocab:dict[str,list[str]])->list[str]:
 text=" ".join(_list(values,50)).casefold()
 return [k for k,phrases in vocab.items() if any(p.casefold() in text for p in phrases)]

def normalize_semantic(data:dict[str,Any])->dict[str,Any]:
 out=dict(data)
 out["situation_ids"]=list(dict.fromkeys(_list(data.get("situation_ids"),12)+_match(data.get("situations"),SITUATIONS)+_match(data.get("concepts"),SITUATIONS)))
 out["intent_ids"]=list(dict.fromkeys(_list(data.get("intent_ids"),8)+_match(data.get("intents"),INTENTS)+_match(data.get("concepts"),INTENTS)))
 relationship=str(data.get("relationship","")).strip().casefold()
 out["relationship"]=relationship if relationship in RELATIONSHIPS else next((k for k,v in RELATIONSHIPS.items() if any(p.casefold() in relationship for p in v)),"")
 reciprocity=str(data.get("reciprocity","")).strip().casefold()
 out["reciprocity"]=reciprocity if reciprocity in RECIPROCITY else next((k for k,v in RECIPROCITY.items() if any(p.casefold() in reciprocity for p in v)),"")
 out["concepts"]=_list(data.get("concepts"),24)
 for sid in out["situation_ids"]:
  for phrase in SITUATIONS.get(sid,[])[:4]:
   if phrase not in out["concepts"]: out["concepts"].append(phrase)
 if out["reciprocity"]:
  for phrase in RECIPROCITY[out["reciprocity"]][:3]:
   if phrase not in out["concepts"]: out["concepts"].append(phrase)
 return out

def normalize_artifact(artifact:dict[str,Any])->dict[str,Any]:
 result=dict(artifact)
 result["understanding"]=normalize_semantic(dict(artifact.get("understanding") or {}))
 result["semantic_sections"]=[normalize_semantic(dict(x)) for x in (artifact.get("semantic_sections") or [])]
 result["temporal_buckets"]=[normalize_semantic(dict(x)) for x in (artifact.get("temporal_buckets") or [])]
 return result
