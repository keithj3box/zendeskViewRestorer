#python imports
import json
import requests
import logging
from logging.handlers import RotatingFileHandler
import datetime

#local imports
from creds import *

#local vars
baseURL = baseURL # Imported from creds file. 'https://INSTANCE.zendesk.com/api/v2/'
now = datetime.datetime.now()

# ZD session
def zendeskAuth():
	uname = '{}/token'.format(zdEmail)
	pw = zdToken
	headers = {'Content-Type': 'application/json'}
	auth = (uname, pw)
	session = requests.Session()
	session.auth = auth
	session.headers=headers
	if session is None:
		logging.critical('\tSession failed to establish')
		quit()
	else:
		logging.info('\tSession established.')
		return session

# Logging
def initLogger():
	logging.basicConfig(format='%(lineno)d - %(asctime)s - %(levelname)s - %(funcName)s - %(message)s', level=logging.INFO)
	handler = RotatingFileHandler('logs/zendeskBackupVerboseAF.log', maxBytes=1000*1024,backupCount=5)
	handler.setLevel(logging.INFO)
	formatter = logging.Formatter('%(lineno)d - %(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
	handler.setFormatter(formatter)
	logging.getLogger('').addHandler(handler)
	return logging


# retrieve list of all views in ZD
def getViews(session):
	counter, allViews = 1, []
	url = baseURL + 'views.json'
	while url is not None:
		r = session.get(url).json()
		# This endpoint returns the results (view), the total number of views (count),
		# and since it's paginated, the url for the next page if there is one.
		count = r['count']
		logging.info('Got ~100 of {} total views from ZD (in pagination cycle {}'.format(count, counter))
		if 'next_page' in r:
			url = r['next_page']
			logging.info('There is a next page: {}'.format(url))
		else:
			url = None
			logging.info('This should be the last page. (No nextPage)')
		views = r['views']
		allViews.append(views)
		counter += 1
	viewToEdit = views[-1]
	print(viewToEdit)
	return viewToEdit, allViews

# Need to alter the data to rewrite. The format that ZD returns from the export
# does not match the format they need to create.
def changeviewToEdit(viewToEdit):

	logging.info('ATTEMPTING TO TRANSFORM VIEW {}'.format(viewToEdit['title']))
	
	# Adding "COPY" to title, but we iterate this function if there is an error so only
	# doing once.
	if 'COPY' not in viewToEdit['title']:
		title = viewToEdit['title'] + ' COPY'
	else:
		pass
	
	# If no conditions in all or any, change to empty dict.
	allPart = viewToEdit['conditions']['all'] if 'all' in viewToEdit['conditions'] else {}
	if allPart == {}:
		logging.info('That\'s weird. There are not "all" conditions. This will not go well.')
	anyPart = viewToEdit['conditions']['any'] if 'any' in viewToEdit['conditions'] else {}
	if anyPart == {}:
		logging.info('No any conditions.')
	# Use original condition if present, or else put timestamp of this script.
	description = viewToEdit['description'] if viewToEdit['description'] is not None else 'Copied on ' +str(now)
	
	# Need to pass only the column id.
	columns = []
	for c in viewToEdit['execution']['columns']:
		columns.append(c['id'])
	
	#Format of what ZD accepts to create a new view.
	x = {'view': {'title': title,
				  'raw_title': viewToEdit['raw_title'],
				  'description': viewToEdit['description'],
				  'active': viewToEdit['active'],
				  'position': viewToEdit['position'],
				  'restriction': viewToEdit['restriction'],
		 		  'all': allPart,	
		 		  'any': anyPart,
		 		  'output': {'columns': columns,
		 				     'group_by': viewToEdit['execution']['group_by'],
		 					 'group_order': viewToEdit['execution']['group_order'],
		 					 'sort_by': viewToEdit['execution']['sort_by'],
		 					 'sort_order': viewToEdit['execution']['sort_order']}}}
	logging.info('View transformed. /gifs magic.')
	return x


# Recreate the view
def createView(session, view):
	logging.info('Now attempting to recreate the view.')
	url = baseURL + 'views.json'
	payload = view
	r = session.post(url, data=json.dumps(payload))
	print('\n\n', r.text, '\n\n')
	
	# Cannot create a new view using a group that has been deleted.
	if 'error' in r.text:
		logging.info('Creating the view returned an error. This is not great, but\
			we will attempt to handle.')
		view = handlePostErrors(r, view)
		return False, view
	else:
		logging.info('View {} successfully recreated!'.format(view['view']['title']))
		return True, view
		



def handlePostErrors(response, view):
	logging.info('Now attempting to handle the error. Wish us luck.')
	response = response.json()
	print(response, type(response))
	errors, numberOfErrors = response['details']['base'], len(response['details']['base'])
	logging.info('There are {} errors:'.format(numberOfErrors))
	for error in errors:
		logging.info('\tError: {}'.format(error))
	for error in errors:
		if 'was deleted' in error['description']:
			
			# The description string looks like this:
					# 'Group 20051282 was deleted and cannot be used'
				# So extracting the group id.
			
			logging.info('It appears that a group used in this view has been deleted.')
			
			# Sometimes there are more than one error so we have to go through them 
			# individually.
			groupIdsToRemove = []
			
			# This one-liner finds all the numerical digits in the error message and 
			# joins them into a single int. 
			groupIdsToRemove.append(int(''.join(filter(str.isdigit, error['description']))))
			
			for groupId in groupIdsToRemove:
				logging.info('Attempt to remove group {} from conditions'.format(groupId))
				
				# Take the 'all conditions' and remove the group conditions for the 
				# groups that no longer exist.
				view['view']['all'] = [a for a in view['view']['all'] if \
						a['field'] == 'group_id' and a['value'] == str(groupId)]
		
		# If there are no valid conditions for this view, which should only really happen
		# for unused, deprecated views, then you simply can't recreate it.
		elif 'View must test for at least' in error['description']:
			
			# Let's write these views to a new file.
			with open('logs/ViewsUnableToCreate.txt', 'a') as f:
				f.write('\nUnable to recreate this view because of a missing valid condition:\n')
				f.write('\tTime is just a construct but you\'ll find this useful anyway: {}\n'.format(now))
				f.write('\tName: {}'.format(view['view']['title']))
			logging.exception('After error handling, there are no valid conditions in \
					this view. This likely means the view was nonfunctional. This view has \
					been recorded in logs/ViewsUnableToCreate.txt.')


	return view


def main():
	logging = initLogger()
	logging.info('\n\nNEW CYCLE STARTING {}\n\n'.format(now))
	session = zendeskAuth()
	viewToEdit, allViews = getViews(session)
	viewToEdit = changeviewToEdit(viewToEdit)
	print(type(viewToEdit), type(session))
	successful, view = createView(session, viewToEdit)
	if successful == False:
		counter = 1
		while counter < 2 and successful == False:
			successful, view = createView(session, view)
			counter += 1



main()	