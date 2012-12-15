from calendar import HTMLCalendar
from calendar import  month_name
from datetime import date, timedelta, datetime
from itertools import groupby
import pdb
from django import forms
from django.forms.forms import Form
from dimagi.utils import make_time
from dimagi.utils.decorators.memoized import memoized
from pact.enums import DAY_SLOTS_BY_IDX
from pact.models import CObservation
import settings



def obs_for_day(this_date, observations):
    #todo, normalize for timezone
#    print "obs for day: %s" % this_date
    ret = filter(lambda x: x['observed_date'].date() == this_date, observations)
    return ret


def merge_dot_day(day_observations):
    """
    Receive an array of CObservations and try to priority sort them and make a json-able array of ART and NON ART submissions
    for DOT calendar display AND ota restore.
    """
    day_dict = {'ART': {'total_doses':0, 'dose_dict': {} }, 'NONART': {'total_doses': 0, 'dose_dict': {}}}

    def cmp_observation(x, y):
        """
        for a given COBservation, do the following.
        1: If it's an addendump trumps all
        2: If it's direct, and other is not direct, direct wins
        3: If both direct, do by earliest date
        4: If neither direct, do by earliest date.

        < -1
        = 0
        > 1
        """
        #Reconcilation handling
        if (hasattr(x, 'is_reconciliation') and getattr(x, 'is_reconciliation')) and (hasattr(y, 'is_reconciliation') and getattr(y, 'is_reconciliation')):
            #sort by earlier date, so flip x,y
            return cmp(y.submitted_date, x.submitted_date)
#            if x.submitted_date > y.submitted_date:
#                # result: x < y
#                return -1
#            elif x.submitted_date < y.submitted_date:
#                # result: x > y
#                return 1
#            elif x.submitted_date == y.submitted_date:
#                return 0
        elif (hasattr(x, 'is_reconciliation') and getattr(x, 'is_reconciliation')) and (not hasattr(y,'is_reconciliation') or not getattr(y, 'is_reconciliation')):
            # result: x > y
            return 1
        elif (not hasattr(x, 'is_reconciliation') or not getattr(x, 'is_reconciliation')) and (hasattr(y, 'is_reconciliation') and getattr(y, 'is_reconciliation')):
            # result: x < y
            return -1

        if x.method == 'direct' and y.method == 'direct':
            #sort by earlier date, so flip x,y
            return cmp(y.encounter_date, x.encounter_date)
        elif x.method == 'direct' and y.method != 'direct':
            #result: x > y
            return 1
        elif x.method != 'direct' and y.method == 'direct':
            #result: x < y
            return -1
        else:
            #sort by earlier date, so flip x,y
            return cmp(y.encounter_date, x.encounter_date)



    for obs in day_observations:
        if obs.is_art:
            dict_to_use = day_dict['ART']
        else:
            dict_to_use = day_dict['NONART']


        if dict_to_use['total_doses'] < obs.total_doses:
            dict_to_use['total_doses'] = obs.total_doses

        if dict_to_use['dose_dict'].get(obs.dose_number, None) is None:
            dict_to_use['dose_dict'][obs.dose_number] = []
        dict_to_use['dose_dict'][obs.dose_number].append(obs)

    for drug_type, wrapper_dict in day_dict.items():
        dose_dict = wrapper_dict['dose_dict']
        for dose_num in dose_dict.keys():
            observations = dose_dict[dose_num]
            #reverse here because our cmp assigns increasing weight by comparison
            observations = sorted(observations, cmp=cmp_observation, reverse=True) #key=lambda x: x.created_date, reverse=True)
            dose_dict[dose_num]=observations
    return day_dict


class DOTCalendarReporter(object):

    patient_casedoc=None
    start_date=None
    end_date=None

    def unique_xforms(self):
        obs = self.dot_observation_range()
#        ret = set([x[]])
        ret = set([x['doc_id'] for x in filter(lambda y: y.is_reconciliation == False, obs)])
        return ret


    @memoized
    def dot_observation_range(self):
        """
        get the entire range of observations for our given date range.
        """
        case_id = self.patient_casedoc._id
        startkey = [case_id, 'observe_date', self.start_date.year, self.start_date.month, self.start_date.day]
        endkey = [case_id, 'observe_date', self.end_date.year, self.end_date.month, self.end_date.day]
        print "Running dots_observation_range"
        print "%s-%s" % (startkey, endkey)
        observations = CObservation.view('pact/dots_observations', startkey=startkey, endkey=endkey).all()
        print "\t%d observations" % (len(observations))
        return observations

    def __init__(self, patient_casedoc, start_date=None, end_date=None):
        """
        patient_casedoc is a CommCareCase document
        """
        self.patient_casedoc = patient_casedoc
        self.start_date = start_date
        if end_date is None:
            self.end_date = make_time()
        else:
            self.end_date=end_date

        if start_date is None:
            self.start_date = end_date - timedelta(days=14)
        else:
            self.start_date=start_date

    @property
    def calendars(self):
        """
        Return calendar(s) spanning OBSERVED dates for the given encounter_date range.
        In reality this could exceed the dates ranged by the encounter dates since the start_date is a 20 day retrospective.

        Return iterator of calendars
        """
        startmonth = self.start_date.month
        startyear = self.start_date.year
        endmonth = self.end_date.month

        currmonth = startmonth
        curryear = startyear
        observations = self.dot_observation_range()
        while currmonth % 13 + 1 <= endmonth:
            cal = DOTCalendar(self.patient_casedoc, observations)
            yield cal.formatmonth(curryear, currmonth)
            currmonth += 1
            if currmonth % 13 == 0:
                #roll over, flip year
                curryear+=1


class DOTCalendar(HTMLCalendar):
    #source: http://journal.uggedal.com/creating-a-flexible-monthly-calendar-in-django/
    cssclasses = ["mon span2", "tue span2", "wed span2", "thu span2", "fri span2", "sat span2", "sun span2"]

    observations = []
    patient_casedoc=None

    def __init__(self, patient_casedoc, observations):
        super(DOTCalendar, self).__init__()
        #self.submissions = self.group_by_day(submissions)
        #self.django_patient = django_patient
        self.patient_casedoc = patient_casedoc
        self.observations = observations

    def formatmonthname(self, theyear, themonth, withyear=True):
        """
        Return a month name as a table row.
        """
        #make sure to roll over year?
        nextyear=theyear
        prevyear=theyear
        if themonth + 1 > 12:
            nextmonth=1
            nextyear=theyear+1
        else:
            nextmonth=themonth+1
        if themonth-1 == 0:
            prevmonth = 12
            prevyear=theyear-1
        else:
            prevmonth=themonth-1

        if withyear:
            s = '%s %s' % (month_name[themonth], theyear)
        else:
            s = '%s' % month_name[themonth]
        ret = []
#        a = ret.append
#        a('<tr>')
#        a('<th colspan="7" class="month" style="text-align:center;">')
#        a('<ul class="pager">')
#        a('<li class="previous"><a href="?month=%d&year=%d">Previous</a></li>' % (prevmonth, prevyear))
#        a('<li class="disabled">')
#        a(s)
#        a('</li>')
#        a('<li class="next"><a href="?month=%d&year=%d">Next</a></li>' % (nextmonth, nextyear))
#        a('</ul>')
#        a('</th>')
#        a('</tr>')
#        return ''.join(ret)
        return '<tr><th colspan="7" class="month">%s</th></tr>' % s



    def formatday(self, day, weekday):
        if day != 0:
            cssclass = self.cssclasses[weekday]
            this_day = date(self.year, self.month, day)
            if date.today() == this_day:
                cssclass += ' today'
            if date.today() < this_day:
                future=True
            else:
                future=False

            day_submissions = obs_for_day(this_day, self.observations)
            if len(day_submissions) > 0:
                cssclass += ' filled'
                body = ['<div class="calendar-cell">']
                day_data = merge_dot_day(day_submissions)

                for drug_type in day_data.keys():
                    body.append('')
                    body.append('<div class="drug-cell">')
                    body.append('<div class="drug-label">%s</div>' % drug_type)

                    drug_total = day_data[drug_type]['total_doses']

                    for dose_num, obs_list in day_data[drug_type]['dose_dict'].items():
                        if len(obs_list) > 0:
                            obs = obs_list[0]
                            if obs.day_slot != '' and obs.day_slot is not None and obs.day_slot != -1:
                                day_slot_string = DAY_SLOTS_BY_IDX.get(int(obs.day_slot), 'Unknown')
                                body.append('<div class="time-label">%s</div>' % day_slot_string)
                            else:
                                #do it by seq?
                                body.append('<div class="time-label">Dose %d</div>' % (int(dose_num) + 1))
                            body.append('<div class="time-cell">')
                            body.append('<div class="observation">')
                            if obs.adherence =='unchecked':
                                body.append('<span style="font-size:85%;color:#888;font-style:italic;">unchecked</span>')
                            else:
                                if obs.adherence == 'empty':
#                                    body.append('<span class="label label-success">Empty</span>')
                                    body.append('<img src="%spact/icons/check.jpg">' % settings.STATIC_URL)
                                elif obs.adherence == 'partial':
#                                    body.append('<span class="label label-warning">Partial</span>')
                                    body.append('<img src="%spact/icons/exclamation-point.jpg">' % settings.STATIC_URL)
                                elif obs.adherence == 'full':
#                                    body.append('<span class="label label-important">Full</span>')
                                    body.append('<img src="%spact/icons/x-mark.png">' % settings.STATIC_URL)

                                if obs.method == 'direct':
#                                    body.append('<span class="label label-info">Direct</span>')
                                    body.append('<img src="%spact/icons/plus.png">' % settings.STATIC_URL)
                                elif obs.method == 'pillbox':
#                                    body.append('<span class="label label-inverse">Pillbox</span>')
                                    body.append('<img src="%spact/icons/bucket.png">' % settings.STATIC_URL)
                                elif obs.method == 'self':
#                                    body.append('<span class="label">Self</span>')
                                    body.append('<img src="%spact/icons/minus.png">' % settings.STATIC_URL)
                            body.append('&nbsp;</div>') #close time-cell
#                            body.append('&nbsp;</div>') #close observation
                        else:
                            #empty observations for this dose_num
                            body.append('<div class="time-label">Dose %d</div>' % (int(dose_num) + 1))
                            body.append('<div class="time-cell">')
                            body.append('<div class="observation">')
                            body.append("empty! &nbsp;</div>")
#                            body.append('&nbsp;</div>')

                        body.append('&nbsp;</div>') #close observation
                    body.append('&nbsp;</div>') # close calendar-cell
                return self.day_cell(cssclass, '%d %s' % (day, ''.join(body)))

            if weekday < 5 and not future:
                missing_link = []
                return self.day_cell(cssclass, "%d %s" % (day, ''.join(missing_link)))
            elif weekday < 5 and future:
                return self.day_cell('future', "%d" % day)
            else:
                return self.day_cell(cssclass, day)
        return self.day_cell('noday', '&nbsp;')

    def formatmonth(self, theyear, themonth, withyear=True):
        """
        Main Entry point
        Return a formatted month as a table.
        """
        self.year, self.month = theyear, themonth
        #return super(SubmissionCalendar, self).formatmonth(year, month)
        #rather than do super, do some custom css trickery
        v = []
        a = v.append
        a('<table border="0" cellpadding="0" cellspacing="0" class="table table-bordered">')
        a('\n')
        a(self.formatmonthname(theyear, themonth, withyear=withyear))
        a('\n')
        a(self.formatweekheader())
        a('\n')
        for week in self.monthdays2calendar(theyear, themonth):
            a(self.formatweek(week))
            a('\n')
        a('</table>')
        a('\n')
        return ''.join(v)

    def group_by_day(self, submissions):
        field = lambda submission: datetime.strptime(submission.form['author']['time']['@value'][0:8], '%Y%m%d').day
        return dict(
            [(day, list(items)) for day, items in groupby(submissions, field)]
        )

    def day_cell(self, cssclass, body):
        return '<td class="%s">%s</td>' % (cssclass, body)
