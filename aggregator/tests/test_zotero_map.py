from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import runpy

import httpx
import pytest

from papercart.build import build_feed, migrate_previous
from papercart.network import Pacer
from papercart.normalize import Paper
from papercart.schema import validate_feed
from papercart.sources import load_sources
from papercart.state import State
from papercart.zotero_map import REPORT_SERIES, TEMPLATE_FIELDS, to_zotero
from test_build import NOW, replay_client

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = Path(__file__).parent / 'fixtures/m3/zotero'
SOURCE_IDS = [s.id for s in load_sources()]


@pytest.fixture(scope='module')
def mapped_feed(tmp_path_factory):
    # Module fixtures run before the function-scoped privacy guard.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv('CROSSREF_MAILTO', 'papercart@example.invalid')
        with replay_client() as client:
            return build_feed(load_sources(), client=client, now=NOW,
                              state=State(tmp_path_factory.mktemp('m3')/'state.json'),
                              pacer=Pacer(sleep=lambda _:None, clock=lambda:0), enrich=False)


@pytest.mark.parametrize('sid', SOURCE_IDS)
def test_source_snapshot(sid, mapped_feed):
    expected = json.loads((SNAPSHOTS/(sid+'.json')).read_text())
    own = [p for p in mapped_feed['papers'] if p['source']==sid]
    if sid == 'bfi':
        assert own == expected['papers'] == []
        assert next(s for s in mapped_feed['sources'] if s['id']==sid)['status'] == expected['status'] == 'disabled'
        return
    paper = next(p for p in own if p['id']==expected['paper_id'])
    assert to_zotero(Paper(**paper)) == expected['zotero'] == paper['zotero']
    assert set(paper['zotero']) <= TEMPLATE_FIELDS[paper['kind']]


@pytest.mark.parametrize('kind', ['journalArticle','report'])
def test_pinned_field_sets_equal_recorded_templates(kind, fixture_json):
    assert TEMPLATE_FIELDS[kind] == frozenset(fixture_json('zotero-'+kind+'.json'))


def paper(**changes):
    base = Paper(id='doi:10.3386/w123',doi='10.3386/w123',source='nber',kind='report',
                 title='Example',authors=[{'given':'Ada','family':'Lovelace'}],abstract='Summary',
                 published='2026-10',url='https://doi.org/10.3386/w123',wp_number='123')
    return replace(base, **changes)


def test_author_name_shapes_and_order():
    item=to_zotero(paper(authors=[{'given':'Ada','family':'Lovelace'},
                                {'given':'','family':'Research Group'}, {'name':'Single Author'},
                                {'given':'OnlyGiven','family':''}, {'given':'','family':''}]))
    assert item['creators'] == [
        {'creatorType':'author','firstName':'Ada','lastName':'Lovelace'},
        {'creatorType':'author','name':'Research Group'},
        {'creatorType':'author','name':'Single Author'},
        {'creatorType':'author','firstName':'OnlyGiven','lastName':''},
    ]


@pytest.mark.parametrize('published',[None,'2026','2026-10','2026-10-12'])
def test_missing_metadata_and_date_precision(published):
    item=to_zotero(paper(doi=None,url='',abstract=None,published=published,wp_number=None,
                         first_seen='2026-10-12T18:00:00Z',authors=[]))
    assert not {'DOI','url','abstractNote','reportNumber','collections','tags'} & set(item)
    assert item.get('date') == published
    assert ('date' in item) == bool(published)
    assert item['creators'] == []


@pytest.mark.parametrize('sid', ['nber','feds','ecb','bis'])
def test_report_source_identity_overrides_generic_rss_institution(sid):
    item=to_zotero(paper(source=sid,institution='Generic feed name',series_title='Generic feed name'))
    institution,series=REPORT_SERIES[sid]
    assert (item['institution'],item['seriesTitle']) == (institution,series)
    assert item['reportType']=='Working Paper' and item['reportNumber']=='123'
    assert item['DOI']=='10.3386/w123'


def test_all_journal_fields_and_no_report_fields():
    item=to_zotero(paper(source='aer',kind='journalArticle',publication_title='American Economic Review',
                         journal_abbreviation='AER',volume='116',issue='9',pages='1–20',issn='0002-8282'))
    assert item == {'itemType':'journalArticle','title':'Example',
                    'creators':[{'creatorType':'author','firstName':'Ada','lastName':'Lovelace'}],
                    'abstractNote':'Summary','DOI':'10.3386/w123','url':'https://doi.org/10.3386/w123',
                    'date':'2026-10','publicationTitle':'American Economic Review','journalAbbreviation':'AER',
                    'volume':'116','issue':'9','pages':'1–20','ISSN':'0002-8282'}


@pytest.mark.parametrize('change',[{'kind':'book'}, {'source':'unknown'}])
def test_unknown_mapping_is_rejected(change):
    with pytest.raises(ValueError):to_zotero(paper(**change))


@pytest.mark.parametrize('mutation',['unknown','collections','tags','wrong_type','journal_field_on_report',
                                    'mixed_name','missing_name','extra_creator_field','bad_creator_type',
                                    'first_seen_as_date','missing_institution','stale_abstract'])
def test_feed_rejects_invalid_zotero(mapped_feed,mutation):
    feed=deepcopy(mapped_feed)
    p=next(p for p in feed['papers'] if p['source']=='nber' and not p['published'])
    item=p['zotero']
    if mutation=='unknown':item['notAField']='x'
    if mutation=='collections':item['collections']=[]
    if mutation=='tags':item['tags']=[]
    if mutation=='wrong_type':item['itemType']='journalArticle'
    if mutation=='journal_field_on_report':item['publicationTitle']='x'
    if mutation=='mixed_name':item['creators']=[{'creatorType':'author','name':'X','firstName':'X','lastName':'Y'}]
    if mutation=='missing_name':item['creators']=[{'creatorType':'author'}]
    if mutation=='extra_creator_field':item['creators']=[{'creatorType':'author','name':'X','fieldMode':1}]
    if mutation=='bad_creator_type':item['creators']=[{'creatorType':'editor','name':'X'}]
    if mutation=='first_seen_as_date':item['date']=p['first_seen'][:10]
    if mutation=='missing_institution':item.pop('institution')
    if mutation=='stale_abstract':item['abstractNote']='Outdated summary'
    with pytest.raises(ValueError):validate_feed(feed)


def test_m2_feed_migration_keeps_publication_dates_and_abstracts(mapped_feed):
    old=deepcopy(mapped_feed)
    for p in old['papers']:p['zotero']={}
    migrated=migrate_previous(old)
    assert migrated==mapped_feed
    assert all(p['zotero']=={} for p in old['papers'])


def test_m2_state_is_remapped_without_network_or_previous_feed(mapped_feed,tmp_path):
    path=tmp_path/'state.json';state=State(path)
    state.remember([replace(Paper(**p),zotero={}) for p in mapped_feed['papers']]);state.save()
    second_state=State(path)
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(503))) as client:
        second=build_feed(load_sources(),client=client,now=NOW+timedelta(hours=1),state=second_state,
                          pacer=Pacer(sleep=lambda _:None,clock=lambda:0),enrich=False)
    assert {p['id']:p['zotero'] for p in second['papers']} == {p['id']:p['zotero'] for p in mapped_feed['papers']}
    second_state.save()
    assert all(p.zotero for p in State(path).history())


def test_mapping_uses_abstract_after_enrichment(monkeypatch,tmp_path):
    from papercart.build import empty_enrichment
    from papercart.enrichment import AbstractEnricher
    def enrich(self, papers):
        return [replace(p,abstract='Newly filled summary') for p in papers], empty_enrichment()
    monkeypatch.setattr(AbstractEnricher,'enrich',enrich)
    with replay_client() as client:
        feed=build_feed(load_sources(),client=client,now=NOW,state=State(tmp_path/'state.json'),
                        pacer=Pacer(sleep=lambda _:None,clock=lambda:0))
    own=[p for p in feed['papers'] if p['source'] in {'nber','jpe'}]
    assert own and all(p['zotero']['abstractNote']=='Newly filled summary' for p in own)


def test_offline_frontend_sample_is_reproducible():
    sample=json.loads((ROOT/'web/src/fixtures/feed.sample.json').read_text())
    regenerate=runpy.run_path(str(ROOT/'aggregator/scripts/make_feed_sample.py'))['make_sample']
    assert regenerate()==sample
    validate_feed(sample)
    assert len(sample['papers'])==36
    for source in sample['sources']:
        own=[p for p in sample['papers'] if p['source']==source['id']]
        assert len(own)==source['count']==(0 if source['id']=='bfi' else 3)
        assert source['abstract_count']==sum(bool(p['abstract']) for p in own)
    ecb=[p for p in sample['papers'] if p['source']=='ecb']
    assert all('.pdf' in p['zotero']['url'] for p in ecb)
