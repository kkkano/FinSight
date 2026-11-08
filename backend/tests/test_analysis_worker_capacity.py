import json
from types import SimpleNamespace

import pytest

from backend.analysis_worker.dispatcher import Dispatcher, Settings
from backend.analysis_worker.data_access import get_frame
from backend.analysis_worker.protocol import safe_code_error


@pytest.mark.parametrize("available,expected", [(255,None),(256,128),(316,128),(320,192),(383,192),(384,256),(800,256)])
def test_adaptive_jobs_respect_available_ram_and_keep_host_reserve(available,expected):
    dispatcher=Dispatcher(Settings(enabled=True,token='test-token-long-enough-for-settings',memory_mb=256,
        reserve_memory_mb=128,adaptive_memory=True,min_memory_mb=128))
    selected=dispatcher.job_memory_mb(available)
    assert selected==expected
    if selected:
        assert selected+128<=available
        args=dispatcher.container_args('job','input',stage=False,memory_mb=selected)
        assert args[args.index('--memory')+1]==args[args.index('--memory-swap')+1]==str(selected)+'m'
        assert args[args.index('--network')+1]=='none'
        assert args[args.index('--user')+1]=='65532:65532'
        assert '--read-only' in args and '--oom-score-adj' in args


def test_stock_envelope_is_available_as_dataframe_without_changing_raw_data():
    data={'source':'provider','currency':'USD','data':[{'time':'2026-01-01','close':100},{'time':'2026-01-02','close':125}]}
    before=json.dumps(data)
    frame=get_frame({'stock':data},'stock')
    assert frame['close'].tolist()==[100,125]
    assert json.dumps(data)==before


def test_earnings_tables_require_explicit_selection():
    data={'earnings_estimate':[{'period':'0q','avg':1.5}], 'eps_revisions':[{'period':'0q','up':2}]}
    with pytest.raises(ValueError,match='多张表'):
        get_frame({'earnings':data},'earnings')
    assert get_frame({'earnings':data},'earnings','earnings_estimate').iloc[0]['avg']==1.5


def test_sec_parallel_columns_remain_aligned():
    payload={'ticker':'AAPL','period_ends':['2026-03-31','2026-06-30'],'revenue':[100,120],'eps':[1,None], 'currency':'USD'}
    frame=get_frame({'sec':payload},'sec')
    assert frame['revenue'].tolist()==[100,120] and frame.attrs['currency']=='USD'
    payload['eps']=[1]
    with pytest.raises(ValueError,match='数量不一致'):
        get_frame({'sec':payload},'sec')


@pytest.mark.parametrize('direct', [False, True])
def test_dataframe_accepts_sec_payload_and_ignores_non_metric_lists(direct):
    payload = {'ticker': 'NVDA', 'period_ends': ['2026-07-26', '2026-04-26'],
               'revenue': [96221000000, 81615000000], 'warnings': [], 'metric_gaps': ['eps'],
               'fact_metadata': {'revenue': [{'unit': 'USD'}, {'unit': 'USD'}]}}
    frame = get_frame({'sec': payload}, payload if direct else 'sec')
    assert frame['revenue'].tolist() == [96221000000, 81615000000]
    assert frame.iloc[0]['fact_metadata']['revenue']['unit'] == 'USD'
    assert 'warnings' not in frame and 'metric_gaps' not in frame
    named = get_frame({'sec': payload}, 'sec', table='companyfacts')
    assert named['period_end'].tolist() == payload['period_ends']
    assert named['period'].tolist() == payload['period_ends']
    assert named['ticker'].tolist() == ['NVDA', 'NVDA']
    payload['revenue'] = [96221000000]
    with pytest.raises(ValueError, match='数量不一致'):
        get_frame({'sec': payload}, payload)


def test_dataframe_accepts_direct_rows():
    assert get_frame({}, [{'close': 10}, {'close': 12}])['close'].mean() == 11


def test_dispatcher_preserves_bounded_debug_output_on_failure():
    payload = {'status': 'error', 'error': 'analysis_result_missing', 'logs': "['date', 'close']\n", 'logs_truncated': False}
    assert Dispatcher.parse_result(json.dumps(payload).encode()) == payload


def test_code_error_has_line_and_message_but_no_credentials():
    value=safe_code_error({'type':'KeyError','message':'api_key=sk-this-should-not-be-shown-12345', 'line':3, 'traceback':'private'})
    assert value['line']==3 and 'this-should-not' not in value['message'] and 'traceback' not in value
    assert safe_code_error({'type':'UntrustedError','message':'hidden'}) is None
