"""Real connection, invoice and preference contracts; all data stays in a temporary DB."""
from __future__ import annotations
import hashlib
import os
import sys
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
_TEMP = tempfile.TemporaryDirectory(prefix='artha-taste-tests-')
os.environ['SHOPPINGHELP_DB_PATH'] = str(Path(_TEMP.name)/'app.sqlite3')
os.environ['SHOPPINGHELP_PRIVATE_DIR'] = str(Path(_TEMP.name)/'private')

from backend.db import db
from backend.profile import get_or_create_profile, ingest_retailer_orders, ingest_gmail_orders, refresh_profile, build_context_graph
from backend.connections import six_month_cutoff, provider_directory, _store_invoice, invoice_file
from backend.taste_memory import save_memories, remember_link, remember_orders, retrieve_memories, public_memories
from backend.workflow import BriefAgent


class TasteContracts(unittest.TestCase):
    def setUp(self):
        self.user = 'test-'+uuid.uuid4().hex

    def order(self, **changes):
        return {'id':'111-1234567-1234567','order_date':'2026-10-01','total':1299.75,
                'items':[{'name':'Blue linen shirt','brand':'Example','category':'Clothing','size':'L','price':1299.75}],
                'location':'Pune 411001','source_url':'https://www.amazon.in/gp/your-account/order-details?orderID=111-1234567-1234567',
                'evidence_hash':'evidence-from-page',**changes}

    def test_empty_profile_never_creates_demo_purchases(self):
        for mode in ('live','fixture'):
            with patch.dict(os.environ,{'SHOPPINGHELP_SEARCH_MODE':mode}):
                profile = get_or_create_profile(self.user)
                self.assertEqual(profile['preferences']['brands'],[])
                self.assertEqual(profile['preferences']['addresses'],[])
                self.assertEqual(profile['stats']['orders_tracked'],0)
                self.assertEqual(profile['preferences']['sizes']['top'],'')

    def test_calendar_six_month_window_handles_month_end(self):
        self.assertEqual(six_month_cutoff(date(2026,10,17)),date(2026,4,17))
        self.assertEqual(six_month_cutoff(date(2025,8,31)),date(2025,2,28))

    def test_shutdown_closes_owned_browser_worker_before_exiting(self):
        from backend import connections
        process=Mock()
        process.poll.return_value=None
        with patch.object(connections,'_jobs',{('test','amazon'):{'process':process}}):
            connections._shutdown()
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=8)
        process.kill.assert_not_called()

    def test_retailer_evidence_is_idempotent_and_preserves_paise(self):
        first = ingest_retailer_orders(self.user,'amazon',[self.order()],date(2026,4,17))
        ingest_retailer_orders(self.user,'amazon',[self.order()],date(2026,4,17))
        self.assertEqual(len(db.list_orders(self.user)),1)
        self.assertEqual(db.list_orders(self.user)[0]['total'],1299.75)
        self.assertEqual(db.list_orders('other-user'),[])
        self.assertEqual(first[0]['data_source'],'retailer_session')
        self.assertEqual(ingest_retailer_orders(self.user,'amazon',[self.order(order_date='2026-01-01')],date(2026,4,17)),[])
        with self.assertRaises(ValueError):
            ingest_retailer_orders(self.user,'amazon',[self.order(evidence_hash='')],date(2026,4,17))

    def test_purchase_memory_and_graph_have_source_evidence(self):
        orders = ingest_retailer_orders(self.user,'amazon',[self.order()],date(2026,4,17))
        with patch('backend.taste_memory.embed_documents',return_value=([[1.0]+[0.0]*31],'test:embedding')):
            remember_orders(self.user,orders)
        profile = refresh_profile(self.user)
        self.assertEqual(profile['preferences']['sizes']['top'],'L')
        self.assertEqual(profile['stats']['vectors_ready'],1)
        graph=build_context_graph(self.user)
        ids={node['id'] for node in graph['nodes']}
        self.assertTrue(all(link['source'] in ids and link['target'] in ids for link in graph['links']))
        self.assertIn('memory',{node['group'] for node in graph['nodes']})
        self.assertEqual(graph['metrics']['tracked_orders'],1)
        order_node=next(node for node in graph['nodes'] if node['group']=='order')
        self.assertEqual(order_node['meta']['price'],'₹1,299.75')
        self.assertNotIn('embedding',public_memories(self.user)[0])

    def test_graph_does_not_report_item_price_as_gmail_order_total(self):
        ingest_gmail_orders(self.user,'amazon',[{'id':'gmail-message-1','order_date':'2026-10-01',
            'evidence_hash':'a'*64,'items':[{'name':'Blue linen shirt','price':1299.75}]}])
        graph=build_context_graph(self.user)
        order_node=next(node for node in graph['nodes'] if node['group']=='order')
        self.assertEqual(order_node['meta']['price'],'Price not exposed by retailer')

    def test_semantic_retrieval_never_reads_another_users_memory(self):
        blue=[1.0]+[0.0]*31
        red=[0.0,1.0]+[0.0]*30
        with patch('backend.taste_memory.embed_documents',return_value=([blue,red],'test:embedding')):
            save_memories(self.user,[{'source_key':'blue','kind':'saved_link','document':'Blue shirt','attributes':{}},
                                     {'source_key':'red','kind':'saved_link','document':'Red boots','attributes':{}}])
        with patch('backend.taste_memory.embed_documents',return_value=([blue],'test:embedding')):
            matches=retrieve_memories(self.user,'blue shirt')
            self.assertEqual(matches['mode'],'hybrid')
            self.assertEqual(matches['memories'][0]['document'],'Blue shirt')
            self.assertEqual(retrieve_memories('different-user','blue shirt')['memories'],[])

    def test_failed_embeddings_keep_evidence_without_fake_vectors(self):
        with patch('backend.taste_memory.embed_documents',side_effect=RuntimeError('offline')):
            result=save_memories(self.user,[{'source_key':'post','kind':'saved_link','document':'Blue linen shirt','attributes':{}}])
        self.assertEqual(result[0]['embedding_status'],'pending')
        self.assertIsNone(db.list_taste_memories(self.user)[0]['embedding'])
        self.assertEqual(retrieve_memories(self.user,'linen')['mode'],'keyword')

    def test_profile_does_not_apply_clothing_size_to_laptop_or_wrong_city(self):
        db.save_user_profile(self.user,{'sizes':{'top':'L'},'vibes':['minimalist'],
             'addresses':[{'city':'Pune','pincode':'411001','is_default':True}]},{'evidence_version':1})
        with patch.dict(os.environ,{'SHOPPINGHELP_SEARCH_MODE':'fixture'}):
            brief,_=BriefAgent().run({'text':'laptop under 50000 in Delhi','use_profile':True,'user_id':self.user})
        self.assertFalse(brief.get('size'))
        self.assertNotEqual(brief.get('pincode'),'411001')
        with patch.dict(os.environ,{'SHOPPINGHELP_SEARCH_MODE':'fixture'}):
            shirt,_=BriefAgent().run({'text':'linen shirt under 2000','use_profile':True,'user_id':self.user})
        self.assertEqual(shirt['mission']['size'],'L')
        self.assertEqual(shirt['mission']['pincode'],'411001')

    def test_unreadable_social_page_does_not_invent_aesthetic(self):
        from backend.social import extract_theme_from_url
        with (patch('backend.social._public_reference_url',return_value=('https://example.com/post','https://example.com/post')),
              patch('backend.social.capture_social_page',return_value={'success':False})):
            self.assertFalse(extract_theme_from_url('https://example.com/post')['success'])

    def test_instagram_share_analysis_is_saved_as_private_taste_memory(self):
        from backend.social import extract_theme_from_url
        model=Mock();model.provider='ollama';model.preference='ollama'
        model.ollama.extract_brief.return_value={'theme':'earthy relaxed style','colors':['olive','cream'],
            'style_tags':['minimal','weekend'],'summary':'Relaxed earth-tone outfit.'}
        vector=[1.0]+[0.0]*31
        with (patch('backend.social._public_reference_url',return_value=('https://www.instagram.com/p/example/','https://www.instagram.com/p/example/')),
              patch('backend.social.capture_social_page',return_value={'success':True,'title':'Weekend look','description':'','screenshot_base64':'dGVzdA=='}),
              patch('backend.social.BriefModel',return_value=model),
              patch('backend.taste_memory.embed_documents',return_value=([vector],'test:embedding'))):
            result=extract_theme_from_url('https://www.instagram.com/p/example/',user_id=self.user)
            memory=remember_link(self.user,result)
            matches=retrieve_memories(self.user,'earthy weekend look')
        self.assertTrue(result['success'])
        self.assertEqual(memory['kind'],'saved_link')
        saved=public_memories(self.user)[0]
        self.assertEqual(saved['attributes']['theme'],'earthy relaxed style')
        self.assertEqual(saved['source_url'],'https://www.instagram.com/p/example/')
        self.assertEqual(matches['mode'],'hybrid')
        self.assertEqual(matches['memories'][0]['kind'],'saved_link')

    def test_instagram_personal_login_is_not_presented_as_an_account_connector(self):
        from backend.social import extract_theme_from_url
        with (patch('backend.social._public_reference_url',return_value=('https://www.instagram.com/reel/example/','https://www.instagram.com/reel/example/')),
              patch('backend.social.capture_social_page',return_value={'success':False,'requires_login':True})):
            result=extract_theme_from_url('https://www.instagram.com/reel/example/',user_id=self.user)
        self.assertFalse(result['success'])
        self.assertIn('publicly viewable Reel links only',result['error'])

    def test_invoice_is_private_and_validated(self):
        from pypdf import PdfWriter
        directory=provider_directory(self.user,'amazon')
        (directory/'invoices').mkdir(parents=True)
        fixture=Path(_TEMP.name)/'test-invoice.pdf'
        writer=PdfWriter();writer.add_blank_page(width=200,height=200)
        writer.write(fixture)
        content=fixture.read_bytes();digest=hashlib.sha256(content).hexdigest()
        file=directory/'invoices'/f'{digest}.pdf';file.write_bytes(content)
        _store_invoice(self.user,'amazon',{'filename':file.name,'sha256':digest,'retailer_order_id':'r1'},directory)
        invoice=db.list_retailer_invoices(self.user)[0]
        self.assertEqual(invoice_file(self.user,invoice['id']),file)
        self.assertIsNone(invoice_file('another-user',invoice['id']))
        with self.assertRaises(ValueError):
            _store_invoice(self.user,'amazon',{'filename':'../../outside.pdf'},directory)

if __name__=='__main__':
    unittest.main()
