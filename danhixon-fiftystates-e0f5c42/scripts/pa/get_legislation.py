#!/usr/bin/env python
from __future__ import with_statement
import re
import datetime as dt
import calendar
from utils import *

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyutils.legislation import *

class PALegislationScraper(LegislationScraper):

    state = 'pa'

    metadata = {
        'state_name': 'Pennsylvania',
        'legislature_name': 'Pennsylvania General Assembly',
        'upper_chamber_name': 'Senate',
        'lower_chamber_name': 'House of Representatives',
        'upper_title': 'Senator',
        'lower_title': 'Representative',
        'upper_term': 4,
        'lower_term': 2,
        'sessions': [],
        'session_details': {},
        }

    def scrape_metadata(self):
        with self.soup_context("http://www.legis.state.pa.us/cfdocs/legis/home/session.cfm") as session_page:
            for option in session_page.find(id="BTI_sess").findAll('option'):
                if option['value'].endswith('_0'):
                    year1 = int(option['value'][1:5])
                    year2 = year1 + 1
                    session = "%d-%d" % (year1, year2)
            
                    self.metadata['sessions'].append(session)
                    self.metadata['session_details'][session] = {
                        'years': [year1, year2],
                        'sub_sessions': [],
                        }
                else:
                    session = option.string[0:9]
                    self.metadata['session_details'][session][
                        'sub_sessions'].append(option.string)

        # sessions were in reverse-chronological order
        self.metadata['sessions'].reverse()

        return self.metadata

    def scrape_session(self, chamber, session, special=0):
        with self.soup_context(bill_list_url(chamber, session, special)) as bill_list_page:
            bill_link_re =  "body=%s&type=(B|R)&bn=\d+" % bill_abbr(chamber)

            for link in bill_list_page.findAll(href=re.compile(bill_link_re)):
                self.parse_bill(chamber, session, special, link)

    def parse_bill(self, chamber, session, special, link):
        bill_number = link.contents[0]
        type = re.search('type=(B|R|)', link['href']).group(1)
        bill_id = "%s%s %s" % (bill_abbr(chamber), type, bill_number)

        bill_info_url = info_url(chamber, session, special, type, bill_number)

        with self.soup_context(bill_info_url) as info_page:
            title_label = info_page.find(text='Short Title:')
            title = title_label.findNext().contents[0]

            bill = Bill(session, chamber, bill_id, title)
            bill.add_source(bill_info_url)

            self.parse_bill_versions(bill, info_page)

            self.parse_history(bill, history_url(chamber, session, special, type, bill_number))
            self.parse_votes(bill, vote_url(chamber, session, special, type, bill_number))

            self.add_bill(bill)

    def parse_bill_versions(self, bill, info_page):
        """
        Grab links to all versions of a bill from its info page.
        """
        pn_table = info_page.find('div', {"class": 'pn_table'})
        text_rows = pn_table.findAll('tr')[1:]

        for row in text_rows:
            text_link = row.td.a
            text_url = 'http://www.legis.state.pa.us%s' % text_link['href']
            text_name = text_link.contents[0].strip()
            bill.add_version(text_name, text_url)

    def parse_history(self, bill, url):
        """
        Grab all history data (actions and votes) for a given bill provided
        the url to its history page.
        """
        bill.add_source(url)
        with self.soup_context(url) as history_page:
            self.parse_sponsors(bill, history_page)
            self.parse_actions(bill, history_page)

    def parse_sponsors(self, bill, history_page):
        """
        Grab all of a bill's sponsors from its history page.
        """
        # Sponsor format changed in 2009
        if int(start_year(bill['session'])) < 2009:
            sponsors = history_page.find(text='Sponsors:').parent.findNext('td').find('td').string.strip().replace(' and', ',').split(', ')
            bill.add_sponsor('primary', sponsors[0])

            for cosponsor in sponsors[1:]:
                bill.add_sponsor('cosponsor', cosponsor)
        else:
            sponsors = history_page.find(text='Sponsors:').parent.findNext().findAll('a')
            bill.add_sponsor('primary', sponsors[0].contents[0])

            for cosponsor in sponsors[1:]:
                bill.add_sponsor('cosponsor', cosponsor.contents[0])

    def parse_actions(self, bill, history_page):
        """
        Grab all of a bill's actions from its history page.
        """
        act_table = history_page.find(text="Actions:").parent.findNextSibling()
        act_chamber = bill['chamber']

        for row in act_table.findAll('tr'):
            act_raw = ""
            for node in row.td.div:
                if hasattr(node, 'contents'):
                    if len(node.contents) > 0:
                        act_raw += node.contents[0]
                else:
                    act_raw += node
            act_raw = act_raw.replace('&#160;', ' ')
            act_match = re.match('(.*),\s+((\w+\.?) (\d+), (\d{4}))', act_raw)

            if act_match:
                date = parse_action_date(act_match.group(2).strip())
                bill.add_action(act_chamber, act_match.group(1),
                                date)
            else:
                # Handle actions from the other chamber
                # ("In the (House|Senate)" row followed by actions that
                # took place in that chamber)
                cham_match = re.match('In the (House|Senate)', act_raw)
                if not cham_match:
                    # Ignore?
                    continue

                if cham_match.group(1) == 'House':
                    act_chamber = 'lower'
                else:
                    act_chamber = 'upper'

    def parse_votes(self, bill, url):
        """
        Grab all of the votes for a bill given the url of its primary
        votes page.
        """
        bill.add_source(url)
        with self.soup_context(url) as votes_page:
            for td in votes_page.findAll('td', {'class': 'vote'}):
                prev = td.findPrevious().contents[0].strip()
                if prev == 'Senate':
                    chamber = 'upper'
                    location = ''
                elif prev == 'House':
                    chamber = 'lower'
                    location = ''
                else:
                    # Committee votes come in a number of different formats
                    # that we don't handle yet
                    continue

                chamber_votes_url = td.a['href']
                self.parse_chamber_votes(chamber, bill, chamber_votes_url)

    def parse_chamber_votes(self, chamber, bill, url):
        """
        Grab all votes for a bill that occurred in a given chamber.
        """
        bill.add_source(url)
        with self.soup_context(url) as chamber_votes_page:
            for link in chamber_votes_page.findAll('a', href=re.compile('rc_view')):
                vote_details_url = "http://www.legis.state.pa.us/CFDOCS/Legis/RC/Public/%s" % link['href']
                vote = self.parse_vote_details(vote_details_url)

                date = link.parent.parent.td.contents[0].strip(' \r\n\t-')
                date = dt.datetime.strptime(date, "%m/%d/%Y")

                if link.contents[0].find(',') >= 0:
                    motion = link.contents[0].split(', ')[1].strip()
                else:
                    motion = "Vote"

                vote['motion'] = motion
                vote['date'] = date
                vote['chamber'] = chamber

                bill.add_vote(vote)

    def parse_vote_details(self, url):
        """
        Grab the details of a specific vote, such as how each legislator
        voted.
        """
        with self.soup_context(url) as vote_page:
            header = vote_page.find('div', {'class': 'subHdrGraphic'})
            info_tbl = header.findNext('table')

            motion = info_tbl.findAll('tr')[1].td.contents[-1].strip()
            date = info_tbl.findAll('tr')[2].findAll('td')[-1].contents[0].strip()
            date = dt.datetime.strptime(date, "%m/%d/%Y")

            yes_count = int(info_tbl.find(text=" YEAS").findPrevious().contents[0])
            no_count = int(info_tbl.find(text=" NAYS").findPrevious().contents[0])
            lve_count = int(info_tbl.find(text=" LVE").findPrevious().contents[0])
            nv_count = int(info_tbl.find(text=" N/V").findPrevious().contents[0])
            other_count = lve_count + nv_count

            passed = yes_count > no_count

            vote = Vote(None, None, None, passed, yes_count, no_count,
                        other_count)
            vote.add_source(url)

            vote_tbl = header.findNext('div').findAll('table')[2]
            for yes in vote_tbl.findAll(text=re.compile('^Y$')):
                vote.yes(yes.findNext().contents[0])
            for no in vote_tbl.findAll(text=re.compile('^N$')):
                vote.no(no.findNext().contents[0])
            for other in vote_tbl.findAll(text=re.compile('^(X|E)$')):
                vote.other(other.findNext().contents[0])

        return vote

    def scrape_bills(self, chamber, year):
        session = "%s-%d" % (year, int(year) + 1)
        if not session in self.metadata['session_details']:
            raise NoDataForYear(year)

        self.scrape_session(chamber, session)
        for special in self.metadata['session_details'][session]['sub_sessions']:
            session_num = re.search('#(\d+)', special).group(1)
            self.scrape_session(chamber, session, int(session_num))

    def scrape_legislators(self, chamber, year):
        # Pennsylvania doesn't make member lists easily available
        # for previous sessions, unfortunately
        if int(year) < 2009:
            #raise NoDataForYear(year)
            return

        session = "%s-%d" % (year, int(year) + 1)
        leg_list_url = legislators_url(chamber)

        with self.soup_context(leg_list_url) as member_list_page:

            for link in member_list_page.findAll('a', href=re.compile('_bio\.cfm\?id=')):
                full_name = link.contents[0][0:-4]
                last_name = full_name.split(',')[0]
                first_name = full_name.split(' ')[1]

                if len(full_name.split(' ')) > 2:
                    middle_name = full_name.split(' ')[2].strip(',')
                else:
                    middle_name = ''

                party = link.contents[0][-2]
                if party == 'R':
                    party = "Republican"
                elif party == 'D':
                    party = "Democrat"

                district = re.search("District (\d+)", link.parent.contents[1]).group(1)

                legislator = Legislator(session, chamber, district,
                                        full_name, first_name, last_name,
                                        middle_name, party)
                legislator.add_source(leg_list_url)
                self.add_legislator(legislator)

if __name__ == '__main__':
    PALegislationScraper().run()
