"""V1.5.1 structured understanding of user questions."""
from __future__ import annotations
import json, logging
from typing import Any, Callable
from .llm import ollama_chat
log=logging.getLogger(__name__)
CONTROLLED={"situation_ids":{"unrequited_love":["एकतरफा प्रेम","अप्रत्युत्तरित प्रेम","प्रेम का प्रत्युत्तर न मिलना","सामने वाला प्रेम न करे","प्रेम को न समझना","one sided love","unrequited love","love is not reciprocated"],"attachment_in_love":["प्रेम में आसक्ति","प्रेम में अपेक्षा","emotional attachment"],"relationship_conflict":["रिश्ते में विवाद","relationship conflict"],"grief_separation":["वियोग","बिछड़ना","separation","grief"],"anxiety_fear":["चिंता","भय","घबराहट","anxiety","fear"],"anger":["क्रोध","गुस्सा","anger"],"jealousy":["ईर्ष्या","जलन","jealousy"],"temptation":["वासना","लालच","प्रलोभन","temptation"],"devotional_practice":["भक्ति","साधना","नाम जप","devotional practice"]},"intent_ids":{"seek_guidance":["क्या करना चाहिए","क्या करें","मार्गदर्शन","what should i do","seek guidance"],"understand_teaching":["अर्थ क्या है","समझना","what does it mean","understand"],"seek_practice":["कैसे करें","अभ्यास","how to practice"],"seek_reassurance":["आश्वासन","सांत्वना","reassurance"]}}
def _list(value:Any,limit:int=12)->list[str]:
 if not isinstance(value,list): return []
 out=[];seen=set()
 for item in value:
  if not isinstance(item,str): continue
  value=" ".join(item.split()).strip()
  if not value or value.casefold() in seen: continue
  seen.add(value.casefold());out.append(value)
  if len(out)>=limit: break
 return out
def _ids_from_text(value:Any,vocabulary:dict[str,list[str]])->list[str]:
 text=(" ".join(str(x) for x in value) if isinstance(value,list) else str(value or "")).casefold()
 return [key for key,phrases in vocabulary.items() if any(p.casefold() in text for p in phrases)]
def understand_query(question:str,*,llm_call:Callable[...,str]=ollama_chat)->dict[str,Any]:
 prompt=f"""Understand this user question for retrieval against a Hindi Bhajan Marg transcript corpus.
USER QUESTION:
{question}
Extract only what is explicitly or strongly implied. Do not answer. Preserve negation, uncertainty, entities, emotions, and requested action.
Use controlled IDs where applicable: situation_ids={list(CONTROLLED["situation_ids"])} intent_ids={list(CONTROLLED["intent_ids"])}
Return JSON: {{"language":"hi|hinglish|en|mixed|unknown","domain":"","situation":"","intent":"","situation_ids":[],"intent_ids":[],"relationship":"romantic|family|friendship|devotional|","reciprocity":"not_reciprocated|uncertain|reciprocated|","entities":[],"emotions":[],"constraints":[],"concepts":[],"retrieval_phrases":[]}}
retrieval_phrases must express the same situation and intent, not generic advice."""
 try:
  parsed=json.loads(llm_call([{"role":"user","content":prompt}],temperature=0.0,json_mode=True,num_predict=900))
  if not isinstance(parsed,dict): raise ValueError("query intent is not an object")
 except Exception as exc:
  log.warning("query intent unavailable: %s",type(exc).__name__);parsed={}
 situation_ids=_list(parsed.get("situation_ids"),8);intent_ids=_list(parsed.get("intent_ids"),6)
 for x in _ids_from_text([parsed.get("situation",""),*parsed.get("retrieval_phrases",[])],CONTROLLED["situation_ids"]):
  if x not in situation_ids:situation_ids.append(x)
 for x in _ids_from_text([parsed.get("intent",""),*parsed.get("retrieval_phrases",[])],CONTROLLED["intent_ids"]):
  if x not in intent_ids:intent_ids.append(x)
 phrases=_list(parsed.get("retrieval_phrases"),8)
 for sid in situation_ids:
  for phrase in CONTROLLED["situation_ids"].get(sid,[])[:4]:
   if phrase not in phrases:phrases.append(phrase)
 for iid in intent_ids:
  for phrase in CONTROLLED["intent_ids"].get(iid,[])[:3]:
   if phrase not in phrases:phrases.append(phrase)
 return {"language":str(parsed.get("language","unknown")),"domain":str(parsed.get("domain","")),"situation":str(parsed.get("situation","")),"intent":str(parsed.get("intent","")),"situation_ids":situation_ids[:8],"intent_ids":intent_ids[:6],"relationship":str(parsed.get("relationship","")),"reciprocity":str(parsed.get("reciprocity","")),"entities":_list(parsed.get("entities")),"emotions":_list(parsed.get("emotions")),"constraints":_list(parsed.get("constraints")),"concepts":_list(parsed.get("concepts"),12),"retrieval_phrases":phrases[:12] or [question]}
def _teaching_queries(intent:dict[str,Any])->list[str]:
 out=[]; situations=set(_list(intent.get("situation_ids"),8))
 if "unrequited_love" in situations: out+=["सामने वाला प्रेम न समझे तो क्या करना चाहिए","जिससे प्रेम करें वह प्रेम न करे तो क्या करें","प्रेम का प्रत्युत्तर न मिले तो क्या करें"]
 if "attachment_in_love" in situations: out+=["प्रेम में आसक्ति और अपेक्षा हो तो क्या करें","प्रेम में मोह छोड़ने का मार्ग"]
 if "relationship_conflict" in situations: out+=["रिश्ते में विवाद हो तो क्या करें","संबंध में मनमुटाव कैसे संभालें"]
 if "grief_separation" in situations: out+=["वियोग और बिछड़ने के दुख में क्या करें"]
 return out
def intent_to_queries(intent:dict[str,Any],original:str)->list[str]:
 values=[original]
 for key in ("situation","intent","relationship","reciprocity"):
  value=str(intent.get(key,"")).strip()
  if value and value not in values:values.append(value)
 for key in ("situation_ids","intent_ids"):
  for value in _list(intent.get(key),8):
   if value not in values:values.append(value)
 for value in _teaching_queries(intent):
  if value not in values:values.append(value)
 for value in _list(intent.get("retrieval_phrases"),10):
  if value not in values:values.append(value)
 concepts=_list(intent.get("concepts"),8)
 if concepts:values.append(" ".join(concepts))
 return values[:12]
