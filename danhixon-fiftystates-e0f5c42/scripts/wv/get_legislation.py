#!/usr/bin/env python
import urllib, re
from BeautifulSoup import BeautifulSoup as BS
import datetime as dt

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyutils.legislation import *

def cleansource(data):
    '''Remove some irregularities from WV's HTML.

It includes a spurious </HEAD> before the useful data begins and lines like '<option value="Bill"selected="selected">Bill</option>', in which the lack of a space between the attributes confuses BeautifulSoup.
'''
    data = data.replace('</HEAD>', '')
    return re.sub('(="[^"]+")([a-zA-Z])', r'\1 \2', data)

def cleansponsor(sponsor):
    if sponsor.endswith('President)'):
        ## in the senate:
        ## Soandso (Salutation President)
        return sponsor.split(' ')[0]
    if ' Speaker' in sponsor: # leading space in case there is a Rep. Speaker
        ## in the house:
        ## Salutation Speaker (Salutation Soandso)
        return sponsor.split(' ')[-1][:-1]
    return sponsor

def issponsorlink(a):
    if 'title' in a:
        return (a['title'].startswith('View bills Delegate') or
                a['title'].startswith('View bills Senator'))
    return False

def sessionexisted(data):
    return not re.search('Please choose another session', data)

urlbase = 'http://www.legis.state.wv.us/Bill_Status/%s'

class WVLegislationScraper(LegislationScraper):

    state = 'wv'

    metadata = {
        'state_name': 'West Virginia',
        'legislature_name': 'The West Virginia Legislature',
        'lower_chamber_name': 'House of Delegates',
        'upper_chamber_name': 'Senate',
        'lower_title': 'Delegate',
        'upper_title': 'Senator',
        'lower_term': 2,
        'upper_term': 4,
        'sessions': map(str, xrange(1993, 2010)),
        'session_details': {}}

    def scrape_metadata(self):
        for year in self.metadata['sessions']:
            self.metadata['session_details'][year] = {
                'years': [int(year)],
                'sub_sessions': []}

            for sub in ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th']:
                self.metadata['session_details'][year]['sub_sessions'].append(
                    "%s %s special session" % (year, sub))

        return self.metadata

    session_abbrevs = 'RS 1X 2X 3X 4X 5X 6X 7X'.split()

    def scrape_bills(self, chamber, year):
        if int(year) < 1993:
            raise NoDataForYear

        for session in self.session_abbrevs:
            if not self.scrape_session(chamber, session, year):
                return

    def scrape_session(self, chamber, session, year):
        if chamber == 'upper':
            c = 's'
        else:
            c = 'h'

        q = 'Bills_all_bills.cfm?year=%s&sessiontype=%s&btype=bill&orig=%s' % (year, session, c)

        try:
            with self.urlopen_context(urlbase % q) as data:
                if not sessionexisted(data):
                    return False
                soup = BS(cleansource(data))
                rows = soup.findAll('table')[1].findAll('tr')[1:]
                for row in rows:
                    histlink = urlbase % row.td.a['href']
                    billid = row.td.a.contents[0].contents[0]
                    self.scrape_bill(chamber, session, billid, histlink, year)
                return True
        except urllib2.HTTPError as e:
            if e.code == 500:
                # Nonexistent session
                return False
            else:
                raise e

    def scrape_bill(self, chamber, session, billid, histurl, year):
        if year[0] != 'R':
            session = year
        else:
            session = self.metadata['session_details'][year]['sub_sessions'][int(year[0]) - 1]

        with self.urlopen_context(histurl) as data:
            soup = BS(cleansource(data))
            basicinfo = soup.findAll('div', id='bhistleft')[0]
            hist = basicinfo.table

            sponsor = None
            title = None
            for b in basicinfo.findAll('b'):
                if b.next.startswith('SUMMARY'):
                    title = b.findNextSiblings(text=True)[0].strip()
                elif b.next.startswith('SPONSOR'):
                    for a in b.findNextSiblings('a'):
                        if not issponsorlink(a):
                            break
                        sponsor = cleansponsor(a.contents[0])

            bill = Bill(session, chamber, billid, title)

            if sponsor:
                bill.add_sponsor('primary', sponsor)

            for row in hist.findAll('tr'):
                link = row.td.a
                vlink = urlbase % link['href']
                vname = link.contents[0].strip()
                bill.add_version(vname, vlink)

            history = soup.findAll('div', id='bhisttab')[0].table
            rows = history.findAll('tr')[1:]
            for row in rows:
                tds = row.findAll('td')
                if len(tds) < 2:
                    # This is not actually an action
                    continue
                date, action = row.findAll('td')[:2]
                date = dt.datetime.strptime(date.contents[0], '%m/%d/%y')
                action = action.contents[0].strip()
                if 'House' in action:
                    actor = 'lower'
                elif 'Senate' in action:
                    actor = 'upper'
                else: # for lack of a better
                    actor = chamber

                bill.add_action(actor, action, date)

        self.add_bill(bill)

if __name__ == '__main__':
    WVLegislationScraper().run()
