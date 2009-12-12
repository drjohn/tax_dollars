#!/usr/bin/env python
import urllib2
import re
import datetime as dt
import html5lib

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyutils.legislation import *

class UTLegislationScraper(LegislationScraper):

    state = 'ut'
    soup_parser = html5lib.HTMLParser(
        tree=html5lib.treebuilders.getTreeBuilder('beautifulsoup')).parse

    # TODO: Grab sessions/sub_sessions programmatically from the site
    metadata = {'state_name': 'Utah',
                'legislature_name': 'Utah State Legislature',
                'lower_chamber_name': 'House of Representatives',
                'upper_chamber_name': 'Senate',
                'lower_title': 'Representative',
                'upper_title': 'Senator',
                'lower_term': 2,
                'upper_term': 4,
                'sessions': ['1997', '1998', '1999', '2000', '2001', '2002',
                             '2003', '2004', '2005', '2006', '2007', '2008',
                             '2009'],
                'session_details':
                {'1997': {'years': [1997],
                          'sub_sessions': ['1997 S1', '1997 S2']},
                 '1998': {'years': [1998], 'sub_sessions': []},
                 '1999': {'years': [1999], 'sub_sessions': []},
                 '2000': {'years': [2000], 'sub_sessions': []},
                 '2001': {'years': [2001],
                          'sub_sessions': ['2001 S1', '2001 S2']},
                 '2002': {'years': [2002],
                          'sub_sessions': ['2002 S2', '2002 S3', '2002 S4',
                                           '2002 S5', '2002 S6']},
                 '2003': {'years': [2003],
                          'sub_sessions': ['2003 S1', '2003 S2']},
                 '2004': {'years': [2004],
                          'sub_sessions': ['2003 S3', '2003 S4']},
                 '2005': {'years': [2005],
                          'sub_sessions': ['2004 S1', '2004 S2']},
                 '2006': {'years': [2006],
                          'sub_sessions': ['2006 S3', '2006 S4', '2006 S5']},
                 '2007': {'years': [2007],'sub_sessions': ['2007 S1']},
                 '2008': {'years': [2008], 'sub_sessions': ['2008 S2']},
                 '2009': {'years': [2009], 'sub_sessions': ['2009 S1']},
                 }
                }

    def scrape_legislators(self, chamber, year):
        if year not in self.metadata['session_details']:
            raise NoDataForYear(year)

        if chamber == 'lower':
            title = 'Representative'
        else:
            title = 'Senator'

        url = 'http://www.le.state.ut.us/asp/roster/roster.asp?year=%s' % year
        leg_list = self.soup_parser(self.urlopen(url))

        for row in leg_list.findAll('table')[1].findAll('tr')[1:]:
            tds = row.findAll('td')

            leg_title = tds[1].find(text=True)
            if leg_title == title:
                fullname = tds[0].find(text=True)
                last_name = fullname.split(',')[0]
                first_name = fullname.split(' ')[1]
                if len(fullname.split(' ')) > 2:
                    middle_name = fullname.split(' ')[2]

                leg = Legislator(year, chamber, tds[3].find(text=True),
                                 fullname, first_name, last_name,
                                 middle_name, tds[2].find(text=True))
                leg.add_source(url)
                self.add_legislator(leg)

    def parse_status(self, bill, url):
        chamber = bill['chamber']
        session = bill['session']
        bill_id = bill['bill_id']
        status = self.soup_parser(self.urlopen(url))
        bill.add_source(url)
        act_table = status.table

        # Get actions
        for row in act_table.findAll('tr')[1:]:
            act_date = row.td.find(text=True)
            act_date = dt.datetime.strptime(act_date, "%m/%d/%Y")
            action = row.findAll('td')[1].find(text=True)

            # If not specified, assume action occurred
            # in originating house
            actor = chamber

            split_action = action.split('/')
            if len(split_action) > 1:
                actor = split_action[0]

                if actor == 'House':
                    actor = 'lower'
                elif actor == 'Senate':
                    actor = 'upper'
                elif actor == 'LFA':
                    actor = 'Office of the Legislative Fiscal Analyst'

                action = '/'.join(split_action[1:]).strip()

            if action == 'Governor Signed':
                actor = 'Governor'

            bill.add_action(actor, action, act_date)

            # Check if this action is a vote
            links = row.findAll('a')
            if len(links) > 1:
                vote_url = links[-1]['href']

                # Committee votes are of a different format that
                # we don't handle yet
                if not vote_url.endswith('txt'):
                    continue

                vote_url = '/'.join(url.split('/')[:-1]) + '/' + vote_url
                vote_page = self.urlopen(vote_url)

                vote_re = re.compile('YEAS -?\s?(\d+)(.*)NAYS -?\s?(\d+)'
                                    '(.*)ABSENT( OR NOT VOTING)? -?\s?'
                                     '(\d+)(.*)',
                                    re.MULTILINE | re.DOTALL)
                match = vote_re.search(vote_page)
                yes_count = match.group(1)
                no_count = match.group(3)
                other_count = match.group(6)

                if int(yes_count) > int(no_count):
                    passed = True
                else:
                    passed = False

                if actor == 'upper' or actor == 'lower':
                    vote_chamber = actor
                    vote_location = ''
                else:
                    vote_chamber = ''
                    vote_location = actor

                vote = Vote(vote_chamber, act_date,
                            action, passed, yes_count, no_count,
                            other_count,
                            location=vote_location)
                vote.add_source(vote_url)

                yes_votes = re.split('\s{2,}', match.group(2).strip())
                no_votes = re.split('\s{2,}', match.group(4).strip())
                other_votes = re.split('\s{2,}', match.group(7).strip())

                map(vote.yes, yes_votes)
                map(vote.no, no_votes)
                map(vote.other, other_votes)

                bill.add_vote(vote)

    def scrape_session(self, chamber, session):
        if chamber == "lower":
            bill_abbr = "HB"
        else:
            bill_abbr = "SB"

        bill_list_url = "http://www.le.state.ut.us/~%s/bills.htm" % (
            session.replace(' ', ''))
        self.log("Getting bill list for %s, %s" % (session, chamber))

        try:
            base_bill_list = self.soup_parser(self.urlopen(bill_list_url))
        except:
            # this session doesn't exist for this year
            return

        bill_list_link_re = re.compile('.*%s\d+ht.htm$' % bill_abbr)

        for link in base_bill_list.findAll('a', href=bill_list_link_re):
            bill_list = self.soup_parser(self.urlopen(link['href']))
            bill_link_re = re.compile('.*billhtm/%s.*.htm' % bill_abbr)

            for bill_link in bill_list.findAll('a', href=bill_link_re):
                bill_id = bill_link.find(text=True).strip()

                bill_info_url = bill_link['href']
                bill_info = self.soup_parser(self.urlopen(bill_info_url))

                (bill_title, primary_sponsor) = bill_info.h3.contents[2].replace('&nbsp;', ' ').strip().split(' -- ')

                bill = Bill(session, chamber, bill_id, bill_title)
                bill.add_source(bill_info_url)
                bill.add_sponsor('primary', primary_sponsor)

                status_re = re.compile('.*billsta/%s.*.htm' % bill_abbr.lower())
                status_link = bill_info.find('a', href=status_re)

                if status_link:
                    self.parse_status(bill, status_link['href'])

                text_find = bill_info.find(text="Bill Text (If you are having trouble viewing PDF files, ")
                if text_find:
                    text_link_re = re.compile('.*\.htm')
                    for text_link in text_find.parent.parent.findAll(
                        'a', href=text_link_re)[1:]:
                        version_name = text_link.previous.strip()
                        bill.add_version(version_name, text_link['href'])

                self.add_bill(bill)

    def scrape_bills(self, chamber, year):
        if year not in self.metadata['session_details']:
            raise NoDataForYear(year)
        session = self.metadata['session_details'][year]

        self.scrape_session(chamber, year)
        for sub_session in session['sub_sessions']:
            self.scrape_session(chamber, sub_session)

if __name__ == '__main__':
    UTLegislationScraper().run()
