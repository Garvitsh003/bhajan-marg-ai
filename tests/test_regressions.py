import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import answer_policy, llm, main, db
from app.budget import deadline, remaining_timeout
from app.chunking import chunk_transcript
from app.text import merge_rolling_caption
from scripts.repair_caption_index import repair_document

CASES = json.loads((Path(__file__).parent/'benchmark_cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=[str(i+1) for i in range(20)])
def test_all_benchmark_questions_stay_standalone(case, monkeypatch):
    model = Mock(side_effect=RuntimeError('provider unavailable'))
    monkeypatch.setattr(llm,'ollama_chat',model)
    history = [{'role':'user','content':'बार-बार क्रोध आने पर क्या करें?'},
               {'role':'assistant','content':'क्रोध के बारे में पिछला उत्तर।'}]
    assert llm.rewrite_query(case['question'],history) == case['question']
    model.assert_not_called()


def test_true_followup_resolves_context(monkeypatch):
    model = Mock(return_value='{"query":"नाम जप करते समय मन भटके तो क्या करें?"}')
    monkeypatch.setattr(llm,'ollama_chat',model)
    assert 'मन भटके' in llm.rewrite_query('और अगर नाम जप करते समय भी मन भटके तो?',
        [{'role':'user','content':'भगवान पर विश्वास कैसे बढ़ाएं?'}])
    model.assert_called_once()


def test_rewrite_failure_only_uses_previous_for_real_reference(monkeypatch):
    monkeypatch.setattr(llm,'ollama_chat',Mock(side_effect=TimeoutError()))
    result=llm.rewrite_query('इससे क्या लाभ होगा?', [{'role':'user','content':'सत्संग क्यों जरूरी है?'}])
    assert 'सत्संग' in result and 'इससे क्या लाभ होगा?' in result


def test_hyphenated_overlap_does_not_drop_god():
    assert merge_rolling_caption('क्या-क्या करना चाहिए?',
        'क्या-क्या करना चाहिए? भगवान से प्रार्थना करनी चाहिए') == 'भगवान से प्रार्थना करनी चाहिए'


def test_combining_marks_and_punctuation_overlap():
    assert merge_rolling_caption('राम, नाम जप करें।','राम, नाम जप करें। और सत्संग सुनें।') == 'और सत्संग सुनें।'
    assert merge_rolling_caption('श्री हरिवंश','श्री हरिवंश') == ''


def test_saved_caption_repair_keeps_original():
    doc={'transcript_source':'youtube_caption:hi.vtt','segments':[
        {'text':'क्या-क्या करना चाहिए?','raw_text':'क्या-क्या करना चाहिए?'},
        {'text':'से प्रार्थना करनी चाहिए','raw_text':'क्या-क्या करना चाहिए? भगवान से प्रार्थना करनी चाहिए'}]}
    repaired,changed=repair_document(doc)
    assert changed == 1 and repaired['segments'][1]['text'].startswith('भगवान')
    assert doc['segments'][1]['text'].startswith('से')


def test_whisper_segments_are_not_treated_as_rolling():
    doc={'transcript_source':'faster_whisper','segments':[
        {'text':'नाम जप करें।','raw_text':'नाम जप करें।'},
        {'text':'नाम जप करें।','raw_text':'नाम जप करें।'}]}
    assert len(repair_document(doc)[0]['segments']) == 2


def test_sentence_split_keeps_connectives_and_punctuation():
    text='भगवान से प्रार्थना करें क्योंकि विश्वास बढ़ता है। अगर मन भटके तो नाम जप करें।'
    assert llm._split_transcript(text) == [
        'भगवान से प्रार्थना करें क्योंकि विश्वास बढ़ता है।','अगर मन भटके तो नाम जप करें।']


@pytest.mark.parametrize('quote',[
    'नाम जप से कल नौकरी पक्की मिल जाएगी।', # invented
    'से प्रार्थना करनी चाहिए।',            # missing subject
    'भगवान से प्रार्थना',                 # incomplete sentence
    'कुसंग छोड़ें।',                      # changed source wording
])
def test_quote_gate_rejects_inventions_fragments_and_paraphrases(quote,monkeypatch):
    monkeypatch.setattr(answer_policy,'_model_json',lambda *a:
        {'quotes':[{'source_index':0,'quote':quote}]})
    assert answer_policy.extract_quotes('विश्वास कैसे बढ़ाएं?',
        [{'transcript_excerpt':'भगवान से प्रार्थना करनी चाहिए। कुसंग का त्याग करें।'}]) == []


def test_quotes_return_in_original_order_with_cue_time(monkeypatch):
    monkeypatch.setattr(answer_policy,'_model_json',lambda *a:{'quotes':[
        {'source_index':0,'quote':'नाम जप करें।'},
        {'source_index':0,'quote':'भगवान से प्रार्थना करनी चाहिए।'}]})
    cues=[{'text':'श्रद्धा कैसे बढ़ाएं?','start_ms':502160,'end_ms':507189},
          {'text':'भगवान से प्रार्थना करनी चाहिए।','start_ms':507199,'end_ms':512948},
          {'text':'नाम जप करें।','start_ms':527000,'end_ms':530000}]
    source={'video_id':'QytmBqULXAs','caption_segments':cues,
            'transcript_excerpt':' '.join(x['text'] for x in cues)}
    quotes=answer_policy.extract_quotes('विश्वास कैसे बढ़ाएं?',[source])
    assert quotes[0]['text'].startswith('भगवान')
    assert quotes[0]['start']=='08:27' and 't=507s' in quotes[0]['url']


def test_evidence_none_remains_empty(monkeypatch):
    monkeypatch.setattr(llm,'ollama_chat',lambda *a,**k:'{"level":"none","source_indices":[]}')
    assert llm.judge_evidence('कल क्या होगा?',[{'context_text':'नाम जप करें।'}],'direct')['source_indices']==[]


def test_failed_judge_does_not_claim_direct_evidence(monkeypatch):
    monkeypatch.setattr(llm,'ollama_chat',Mock(side_effect=TimeoutError()))
    assert llm.judge_evidence('प्रश्न',[{'context_text':'नाम जप करें।'}],'direct')['level']=='related'


def test_extraction_failure_has_explicit_status(monkeypatch):
    monkeypatch.setattr(answer_policy,'extract_quotes',lambda *a:[])
    result=answer_policy.build_answer('कुसंग का प्रभाव?','direct',[{'transcript_excerpt':'कुसंग त्यागें।'}])
    assert result['answer_status']=='source_only' and result['extraction_status']=='unavailable'


def test_unverified_extra_claims_do_not_render(monkeypatch):
    quotes=[{'source_index':0,'text':'नाम जप करें।','start_char':0,'end_char':12}]
    monkeypatch.setattr(answer_policy,'extract_quotes',lambda *a:quotes)
    responses=iter([{'claims':[
        {'section':'interpretation','text':'नाम जप करने का निर्देश है।','quote_ids':[0]},
        {'section':'practical','text':'मोबाइल की रील्स बंद करें।','quote_ids':[0]}]},
        {'checks':[{'id':0,'supported':True},{'id':1,'supported':False}]}])
    monkeypatch.setattr(answer_policy,'_model_json',lambda *a:next(responses))
    result=answer_policy.build_answer('नाम जप?','direct',[{'transcript_excerpt':'नाम जप करें।'}])
    assert 'रील्स' not in result['answer']
    assert 'नाम जप करने का निर्देश' in result['answer']
    assert '[स्रोत 1]' in result['answer']


def test_validation_outage_removes_generated_prose(monkeypatch):
    responses=iter([{'claims':[{'section':'practical','text':'नौकरी मिल जाएगी।','quote_ids':[0]}]}])
    def respond(*args):
        try:return next(responses)
        except StopIteration:raise TimeoutError()
    monkeypatch.setattr(answer_policy,'_model_json',respond)
    claims,status=answer_policy._verified_claims('नाम जप?',[{'source_index':0,'text':'नाम जप करें।'}])
    assert claims==[] and status=='unavailable'


@pytest.mark.parametrize('case',CASES[16:])
def test_adversarial_no_evidence_never_generates_authority(case,monkeypatch):
    model=Mock(side_effect=AssertionError('No external model should be needed'))
    monkeypatch.setattr(answer_policy,'_model_json',model)
    result=answer_policy.build_answer(case['question'],'none',[])
    assert result['answer_status']=='no_evidence'
    assert 'पर्याप्त संदर्भ नहीं मिला' in result['answer']
    model.assert_not_called()


@pytest.fixture
def api_client(monkeypatch,tmp_path):
    monkeypatch.setattr(main,'ensure_collection',lambda:None)
    monkeypatch.setattr(db.settings,'sqlite_path',str(tmp_path/'test.db'))
    with TestClient(main.app,raise_server_exceptions=False) as client:
        yield client


def test_api_upstream_failure_is_readable_across_cors(api_client,monkeypatch):
    monkeypatch.setattr(main,'retrieve',Mock(side_effect=RuntimeError('PRIVATE_PROVIDER_DETAIL')))
    r=api_client.post('/api/chat',json={'question':'सत्संग क्यों जरूरी है?'},
        headers={'Origin':'https://bhajan-marg-ai-web.vercel.app'})
    assert r.status_code==503
    assert r.headers['access-control-allow-origin']=='https://bhajan-marg-ai-web.vercel.app'
    assert r.json()['error']['request_id'] == r.headers['x-request-id']
    assert 'PRIVATE_PROVIDER_DETAIL' not in r.text


def test_api_timeout_and_blank_validation(api_client,monkeypatch):
    monkeypatch.setattr(main,'retrieve',Mock(side_effect=TimeoutError()))
    assert api_client.post('/api/chat',json={'question':'नाम जप?'}).status_code==504
    assert api_client.post('/api/chat',json={'question':'   '}).status_code==422


def test_full_api_contract_and_fresh_search_on_followup(api_client,monkeypatch):
    calls=[]
    monkeypatch.setattr(main,'retrieve',lambda question:
        calls.append(question) or {'level':'none','sources':[],'reason':'No support'})
    monkeypatch.setattr(llm,'ollama_chat',lambda *a,**k:'{"query":"नाम जप का लाभ क्या है?"}')
    first=api_client.post('/api/chat',json={'question':'नाम जप का लाभ?'}).json()
    second=api_client.post('/api/chat',json={'question':'इससे क्या लाभ होगा?',
        'conversation_id':first['conversation_id']}).json()
    assert len(calls)==2 and second['standalone_query']=='नाम जप का लाभ क्या है?'
    assert first['answer_status']=='no_evidence'
    assert len(db.get_messages(first['conversation_id']))==4


def test_request_deadline_is_enforced():
    token=deadline.set(0)
    try:
        with pytest.raises(TimeoutError):remaining_timeout(35)
    finally:deadline.reset(token)


def test_chunk_caption_alignment_preserved():
    cues=[{'segment_id':0,'start_ms':0,'end_ms':1500,'text':'भगवान से प्रार्थना करें।'}]
    assert chunk_transcript(cues)[0]['caption_segments'][0]['text']==cues[0]['text']
