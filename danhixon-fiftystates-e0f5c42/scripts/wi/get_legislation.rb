#!/usr/bin/env ruby
require File.join(File.dirname(__FILE__), '..', 'rbutils', 'new_legislation')
require 'open-uri'
require 'hpricot'

# Hpricot runs out of buffer space (for me) on some pages
Hpricot.buffer_size = 262144

class Wisconsin < LegislationScraper
  @@state = 'wi'
  
  #used internally for iterating through subsessions in a base year
  @@sessions = {}

  def scrape_legislators(chamber, year)
    year = year.to_i
    year = year - 1 if year.even?
    #branch out if we're in the current session
    if Time.now.year == year
      current_legislators(chamber, year.to_s)
    else
      past_legislators(chamber, year.to_s)
    end
  end
  
  def current_legislators(chamber, year)
    words = {'lower' => 'assembly', 'upper' => 'senate'}
    parties = {'D' => 'Democratic', 'R' => 'Republican', 'I' => 'Independent'}
    url = "http://www.legis.state.wi.us/w3asp/contact/legislatorslist.aspx?house=#{words[chamber]}"
    doc = Hpricot(open(url))
    doc = (doc/"td.main table tr")
    doc.each{|row|
      #skip this row if it's a header or spacer.
      cells = row.search("td")
      next if ["h2","hr"].include?(cells.first.children.first.name)
      l = {:session => year, :chamber => chamber }
      cells[0].search("a")[1].inner_html =~ /([\w\-\,\s\.]+)\s+\(([\w])\)/
      l[:full_name], party = $1, $2
      l[:district] = cells[2].inner_html.to_s
      l[:first_name], middle, last = l[:full_name].split(' ')
      if last.nil?
        l[:last_name] = middle
        l[:middle_name] = ""
      else
        l[:last_name] = last
        l[:middle_name] = middle
      end
      l[:party] = parties.include?(party) ? parties[party] : party
      add_legislator(l)
      p "Added #{l[:full_name]}"
    }
  end
  
  def past_legislators(chamber, year)
    throw "No sessions for this year" if @@sessions[year].nil?
    
    @words = {'lower' => 'REPRESENTATIVES', 'upper' => 'SENATORS'}
    parties = {'Dem' => 'Democratic', 'Rep' => 'Republican', 'Ind' => 'Independent'}
    yr = year[2,4]
    path = "Prior%20Sessions/#{year}/indxauth#{yr}/"
    base = "http://nxt.legis.state.wi.us/nxt/gateway.dll?f=xmlcontents&command=getmore&basepathid=#{path}&direction=1&maxnodes=500&minnodesleft=500"
    p base
    doc = Hpricot(open(base))
    doc = (doc/"n[@t=#{@words[chamber]}]")
    path += doc.first['n']
    base = "http://nxt.legis.state.wi.us/nxt/gateway.dll?f=xmlcontents&command=getmore&basepathid=#{path}&direction=1&maxnodes=500&minnodesleft=500"
    doc = Hpricot(open(base)) / "n"
    critters = doc.map{|x| x['t']}
    critters.each{ |legislator|
      l = {:session => year, :chamber => chamber}
      l[:full_name] = legislator[/[\w\s\,\.\-]+/].strip.sub(/ (Rep.)|(Sen.) /,'')
      name = l[:full_name].split(',')
      (l[:first_name], l[:middle_name]) = name[1].split(' ').map{|x|x.sub('.','')}
      l[:last_name] = name[0]
      l[:district] = legislator[/\(\d{1,3}\w{2,3}/][1..-1]
      l.delete(:middle_name) unless l[:middle_name]
      legislator =~ /\;\s(\w+)\.\)/ #party time.
      l[:party] = parties.include?($1) ? parties[$1] : $1
      add_legislator(l)
      p "Added #{l[:full_name]}"
    }
  end
  
  def scrape_bills(chamber, year)
    year = (year.to_i - 1).to_s if year.to_i.even?
    throw "No sessions for this year" if @@sessions[year].nil?
    house = (chamber == 'upper') ? 'S' : 'A'
    @@sessions[year].each{|sess|
      (year, prefix) = sess.first[1..sess.first.length].split('/')
      p sess[1]
      begin
        parse_session(house, year, prefix, sess[1])
      rescue OpenURI::HTTPError => e
        #just ignore it.
      end
    }
  end
  
  def parse_session(fhouse ,fyear, prefix, session)
    chambers = {'S' => 'upper', 'A' => 'lower'}
    pp = {'S' => 'Senate', 'A' => 'House'}
    i = 0
    while i+=1 do
      url = "http://www.legis.state.wi.us/#{fyear}/data/#{prefix}#{fhouse}B#{i}hst.html"
      begin
        data = open(url)
        #hpricot segfaults if there's no data. lovely.
        if data.length == 0 
          p "skipping"
          next
        end
        doc = Hpricot(data)
      rescue OpenURI::HTTPError => e
        url = "http://www.legis.state.wi.us/#{fyear}/#{prefix}/data/#{fhouse}B#{i}hst.html"
        p "retrying with #{url}"
        data = open(url)
        if data.length == 0 
          p "skipping" 
          next 
        end
        doc = Hpricot(data)
      end
      history = doc / 'pre'
      history = history.first.inner_html.split("\n")
      print "Fetching #{pp[fhouse]} Bill #{("%4d" % i)} ... "
      
      bill_id = nil
      title = nil
      sponsers = []
      actions = []
      month,day,year = nil,nil,nil
      date = nil
      house = nil
      stop = false
      
      buffer = ''
      
      history.each{ |line|
        next if line.chomp == ''
        #ok, first we need the title. so.. get it.
        if bill_id.nil?
          topline = (Hpricot(line) / 'a')
          if topline.empty?
            bill_id = line.strip
          else
            bill_id = topline.inner_html
          end
          next
        end

        #don't add the year to our buffer
        if line =~ /^(\d{4})[\s]{0,1}$/
          year = $1
          next
        end
        
        #if there's a date on the line, we know that the last block of
        #info ended, so we need to do something or another with it
        if line =~ /\s+(\d{2})-(\d{2}).\s\s([AS])\.\s/
          month,day,house = $1,$2,$3
          workdata = buffer
          buffer = ''
          stop = true
        else
          stop = false
        end
        buffer += line.strip + ' '
        
        if stop and title.nil?
          title = workdata
          @bill = Bill.new(session, chambers[house], i.to_s, title)
          next
        end
        
        if stop and sponsers.empty? and !(line =~ /Introduced by/)
          date = "#{month}/#{day}/#{year}"
          sponsers = parse_sponsers(workdata)
          sponsers.each{|s|
            @bill.add_sponsor(s[:type], s[:name])
          }
        end
        
        if stop
          d = Time.local(year.to_i, month.to_i, day.to_i)
          actions << parse_action(d.to_i, Hpricot(workdata).to_plain_text, chambers[house])
          if workdata =~ /Ayes (\d+), Noes (\d+)/
            yes,no = $1,$2
            @bill.add_vote(Vote.new(chambers[house], d.to_i, actions.last[:action], (yes > no), yes, no, 0 ))
          end
        end
        #NOW update the date
        date = "#{month}/#{day}/#{year}"
      }
      #we also have the straggler
      d = Time.local(year.to_i, month.to_i, day.to_i)
      actions << parse_action(d.to_i, buffer, chambers[house])
      
      actions.each{|action|
        @bill.add_action(action[:actor], action[:action], action[:date])
      }
      documents = doc / 'pre' / 'a'
      documents.each {|doc|
        @bill.add_document(doc.inner_html, doc['HREF'] )
      }
      add_bill(@bill)
      print "done.\n"
    end
  end
  
  def parse_action(date,action,chamber)
    # "06-18.  S. Received from Assembly  ................................... 220 "
    # "___________                      __________________________________________"
    #    11                                whatever else
    action = action[11,action.length]  #take out the date and house
    action = action[0, action.index(' ..')] if action.index(' ..') #clear out bookkeeping
    
    return {:date => date, :action => action.strip, :actor => chamber}
  end
  
  def parse_sponsers(workdata)
    sponsers = []
    ls = workdata
    start = ls.index("Introduced by")
    ls = ls[start..-1].split(/\sand\s|\,|;/)
    type = ''
    ls.each{|s|
      name = nil
      if s =~ /Introduced/  
        type = 'primary' 
        name = s.split(/Introduced by \w+/).last.strip
      end
      if s =~ /cosponsored/
        type = 'cosponsor' 
        name = s.split(/cosponsored by \w+/).last.strip
      end
      name = s.strip unless name
      sponsers << {:name => name, :type => type}
    }
    return sponsers
  end
  
  def scrape_metadata
 
    details = {
      :state_name => 'Wisconsin',
      :legislature_name =>'The Wisconsin State Legislature',
      :lower_chamber_name =>'Assembly',
      :upper_chamber_name =>'Senate',
      :lower_title =>'Representative',
      :upper_title =>'Senator',
      :lower_term =>2,
      :upper_term =>4
    }
    
    #get a proper list of sessions
    doc = Hpricot(open('http://www.legis.state.wi.us/'))
    s = doc / "select[@id=session] option"
    sessions = []
    session_details = {}
    s.each{|sess|
      text = sess.inner_html
      if text =~ /^(\d{4})/
        year = $1
        sessions << year
        session_details[year] = {:years => [year.to_i, year.to_i + 1], :sub_sessions => [] }
        @@sessions[year] = [[sess['value'],year]]
      elsif text =~ /\w\s(\d{4})/
        year = $1.to_i
        year -= 1 if year %2 == 0
        session_details[year.to_s][:sub_sessions] << text
        @@sessions[year.to_s] << [sess['value'], text]
      end
    }
    details[:sessions] = sessions
    details[:session_details] = session_details

    return details
    end
end
Wisconsin.new.run