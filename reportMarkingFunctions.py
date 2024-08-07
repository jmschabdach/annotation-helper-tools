import pandas as pd
import numpy as np
import random
from annotationHelperLib import *
from dxFilterLibraryPreGrading import *
from IPython.display import clear_output
from google.cloud import bigquery # SQL table interface on Arcus
from collections import Counter 
from datetime import date

numUsersForValidation = 2
 
##
# Regrade skipped reports
# @param client A bigquery client object
# @param project_name A string used to identify the project
# @param grader A string of the grader's name (leave blank to review all flagged reports)
# @param flag The level of "skip" to examine (-1 is group, -2 is clinician)
def regradeSkippedReports(client, project_name="", grader="", flag=-1):   
    # Get the flagged reports
    if grader == "":
        q = "select * from lab.grader_table_with_metadata where grade = "+str(flag)
    else:
        q = "select * from lab.grader_table_with_metadata where grade = "+str(flag)+" and grader_name = '"+grader+"'"
        
    if project_name != "":
        print("Examining the skipped reports for", project_name)
        q += " and project like '%"+project_name+"%'"
        
    q += ";"
    flaggedReports = client.query(q).to_dataframe()
    
    if flaggedReports.shape[0] == 0:
        print("There are currently no reports with the grade of", flag)
    
    # Shuffle the flagged reports
    flaggedReports = flaggedReports.sample(frac=1)
    
    # for each flagged report
    count = 0
    for idx, row in flaggedReports.iterrows():
        clear_output()
        count += 1
        print(str(count)+"/"+str(len(flaggedReports)))
        print()
        # Add a print to show why the report was previously flagged
        # Check if the report is in the lab.skipped_reports table
        checkSkippedQuery = "select * from lab.skipped_reports where proc_ord_id = '"+str(row['proc_ord_id'])
        checkSkippedQuery += "' and grader_name = '"+row['grader_name']+"';"
        skippedDf = client.query(checkSkippedQuery).to_dataframe()
        
        isSkipLogged = False
        if len(skippedDf) == 1:
            isSkipLogged = True
            
        if isSkipLogged:
            print("Reason report was flagged:", skippedDf['skip_reason'].values[0])
        else:
            print("Skipped reason not available.")                                                          
        
        # Print the report
        procOrdId = row['proc_ord_id']
        printReport(procOrdId, client)
        print("Grader: ", row['grader_name'])
        print()
        # ask for grade
        grade = getGrade(enable_md_flag=True)
        print(grade)
        
        if grade != -1 or grade != -2:
            regradeReason = getReason('regrade')

            # Update the grader table with the new grade
            updateQuery = 'UPDATE lab.grader_table_with_metadata set grade = '+str(grade)
            updateQuery += ' WHERE proc_ord_id = "'+str(procOrdId)+'"' 
            updateQuery += ' and grader_name = "' + row['grader_name'] + '"'

            updateJob = client.query(updateQuery)
            updateJob.result()
            
            if isSkipLogged:
                # Update the skipped reports table
                updateSkippedQuery = 'update lab.skipped_reports set grade = '+str(grade)
                updateSkippedQuery += ', regrade_reason = "'+regradeReason+'" '
                updateSkippedQuery += 'where proc_ord_id = "'+str(procOrdId)+'" and '
                updateSkippedQuery += 'grader_name = "' + row['grader_name'] + '";'

                updateSkippedJob = client.query(updateQuery)
                updateSkippedJob.result()
            else:
                # Add the report to the skipped reports table. 
                # ('proc_ord_id', 'grade', 'grader_name', 'skip_date', 'skip_reason', 'regrade_date', 'regrade_reason')
                skipReportQuery = "insert into lab.skipped_reports values ("
                today = date.today().strftime("%Y-%m-%d")
                skipReportQuery += "'"+str(procOrdId)+"',"+str(grade)+", '"+row['grader_name']+"', '', '', '"+today+"', '"+regradeReason+"');"
            
            print("New grade saved. Run the cell again to grade another report.")   
            
    
##
# Print a count of the number of reports graded by each grader since date d
# @param d A string representation of the date in YYYY-MM-DD format
def getGradeCountsSinceDate(d):
    client = bigquery.Client()
    
    # Query the table
    q = 'select * from lab.grader_table_with_metadata where grade_date != "0000-00-00" and cast(grade_date as date) >= cast("'+d+'" as date);'
    df = client.query(q).to_dataframe()
    
    # Get the count of rows for each grader
    graders = list(set(df['grader_name'].values))
    
    # Print the table header
    print("# Reports \t Grader Name")
    
    # Print the rows for each grader
    for grader in graders:
        print(len(df[df['grader_name'] == grader]), '\t\t', grader)
        
    # Print a statement about who has not graded any reports
    print()
    print("Any graders not in the displayed table have not graded any reports since before "+d)
    
    
##
# Iteratively show the user all of the SLIP/non SLIP example reports in a random order (training step 1)
# @param toHighlight A dictionary with str keys specifying a color to highlight the list of str text with
def readSampleReports(toHighlight = {}):

    # Initialize the client service
    client = bigquery.Client()
    
    # Get the SLIP and non-SLIP example reports
    getSlipExamples = 'SELECT * FROM lab.training_examples;'

    slipDf = client.query(getSlipExamples).to_dataframe()

    slipReportsList = [ row['narrative_text'] + '\n\nIMPRESSION: ' + str(row['impression_text']) + '\n\nReport given grade of ' + str(row['grade']) for i, row in slipDf.iterrows()]
        
    # Shuffle the list of all reports
    random.shuffle(slipReportsList)
    
    # Iteratively print each report
    for report in slipReportsList:
        # If the user passed a dictionary of lists to highlight
        if len(toHighlight.keys()) > 0:
            reportText = report
            for key in toHighlight.keys():
                reportText = markTextColor(reportText, toHighlight[key], key)
            
            # Print the report and ask for a grade
            print(reportText)
        else:
            print(report)
    
        print()
    
        confirm = str(input('After you read the report and understand its grade, press ENTER to continue to the next report.'))
        clear_output()
        
    print('You have finished reading the example reports. Rerun this cell to read them again or proceed to the next section.')
    

##
# Add reports for the user to grade for the self-eval
# @param name A str containing the full name of the grader (to also be referenced in publications)
def addSelfEvalReports(name):
    client = bigquery.Client()
    
    queryGetSelfEval = "select distinct report_id from lab.training_selfeval;"
    selfEvalDf = client.query(queryGetSelfEval).to_dataframe()
    reportIds = selfEvalDf['report_id'].values
    
    queryInsertReport = "INSERT into lab.training_selfeval (report_id, grade, grader_name, reason) VALUES"
    
    for report in reportIds:
        queryInsertReport += " ('"+str(report)+"', 999, '"+name+"', ' '),"
    
    queryInsertReport = queryInsertReport[:-1] + ";"
    print("Adding "+str(len(reportIds))+" self-evaluation reports for "+name+" to grade.")
    addReportJob = client.query(queryInsertReport)
    addReportJob.result()
    
##
# Pull the report associated with a proc_ord_id for which the specified grader has a grade of 999, and then grade the report. Modifies lab.grader_table
# @param name A str containing the full name of the grader (to also be referenced in publications)
# @param toHighlight A dictionary with str keys specifying a color to highlight the list of str text with
def markSelfEvalReportSQL(name, toHighlight = {}):

    # Initialize the client service
    client = bigquery.Client()
    
    # Get a row from the grader table for the specified rater that has not been graded yet
    getSingleRowQuery = 'SELECT * FROM lab.training_selfeval WHERE grader_name like "' + name + '" and grade = 999 LIMIT 1'

    df = client.query(getSingleRowQuery).to_dataframe()
    
    if len(df) == 0:
        print("There are currently no reports to grade for", name, " in the table. You have completed the self-evaluation.")
        return
    
    # Get the report for that proc_ord_id from the primary report table
    getReportRow = 'SELECT * FROM arcus_2023_05_02.reports_annotations_master where combo_id = "'+str(df['report_id'].values[0])+'"'
    reportDf = client.query(getReportRow).to_dataframe()
    print(reportDf.shape)
    print(list(reportDf))
    
    # Combine the narrative and impression text
    reportText = reportDf['narrative_text'].values[0] 
    if reportDf['impression_text'].values[0] != 'nan':
        reportText += ' IMPRESSION:' + reportDf['impression_text'].values[0]
    
    # If the user passed a dictionary of lists to highlight
    if len(toHighlight.keys()) > 0:
        for key in toHighlight.keys():
            reportText = markTextColor(reportText, toHighlight[key], key)
            
    # Print the report and ask for a grade
    print(reportText)
    print()
    grade = str(input('Assign a SLIP rating to this report (0 do not use/1 maybe use/2 definitely use): '))
    while grade != "0" and grade != "1" and grade != "2":
        grade = str(input('Invalid input. Assign a SLIP rating to this report (0 do not use/1 maybe use/2 definitely use): '))
    print()
    
    # Update the grader table with the new grade
    updateQuery = 'UPDATE lab.training_selfeval set grade = '+str(grade)
    updateQuery += ' WHERE report_id like "'+str(df['report_id'].values[0])+'"'
    updateQuery += ' and grader_name like "' + name + '"'

    updateJob = client.query(updateQuery)
    updateJob.result()
    
    # Ask for a reason the report was given the grade it was
    reason = str(input('Why does this report get that grade? '))
    print()

    # Update the grader table with the new grade
    updateQuery = 'UPDATE lab.training_selfeval set reason="'+ reason + '"'
    updateQuery += ' WHERE report_id like "'+str(df['report_id'].values[0]) + '"'
    updateQuery += ' and grader_name like "' + name + '"'

    updateJob = client.query(updateQuery)
    updateJob.result()
    
    # Print out the grade and reason Jenna gave the report
    print()
    truthQuery = 'SELECT grade, reason from lab.training_selfeval WHERE report_id like "'+str(df['report_id'].values[0])
    truthQuery += '" and grader_name not like "'+name+'"'
    
    truthDf = client.query(truthQuery).to_dataframe()
    print("For reference, other graders have given this report the following grades for the specified reasons:")
    print()
    for idx, row in truthDf.iterrows():
        if int(row['grade']) != 999:
            print("Grade:", row['grade'], "For reason:", row['reason'])
    
    print()
    confirmContinue = str(input('Press enter to continue'))
          
    print("Grade saved. Run the cell again to grade another report.")
    
##
# Pull the report associated with a proc_ord_id for which the specified grader has a grade of 999, and then grade the report. Modifies lab.grader_table
# @param name A str containing the full name of the grader (to also be referenced in publications)
# @param toHighlight A dictionary with str keys specifying a color to highlight the list of str text with
def markOneReportSQL(name, project, toHighlight = {}):

    # Initialize the client service
    client = bigquery.Client()
    
    # Get a row from the grader table for the specified rater that has not been graded yet - start with Reliability
    getSingleRowQuery = 'SELECT * FROM lab.grader_table_with_metadata grader inner join arcus_2023_04_05.procedure_order_narrative narr on narr.proc_ord_id = grader.proc_ord_id WHERE grader_name = "' + name + '" and grade = 999 and grade_category = "Reliability" LIMIT 1'
    df = client.query(getSingleRowQuery).to_dataframe()
    source_table = "arcus_2023_04_05.procedure_order_narrative"
    
    if len(df) == 0:
        # Get a row from the grader table for the specified rater that has not been graded yet - if no Reliability, then Unique
        getSingleRowQuery = 'SELECT * FROM lab.grader_table_with_metadata WHERE grader_name = "' + name + '" and grade = 999 and grade_category = "Unique" LIMIT 1'
        df = client.query(getSingleRowQuery).to_dataframe()
        source_table = "arcus.procedure_order_narrative"
    
    if len(df) == 0:
        print("There are currently no reports to grade for", name, " in the table. Please add more to continue.")
        return
    
    print("Year of scan:", df['proc_ord_year'].values[0])
    print("Age at scan:", np.round(df['age_in_days'].values[0]/365.25, 2), "years")
    procOrdId = df['proc_ord_id'].values[0]
    printReport(procOrdId, client, toHighlight, source_table) # -- LOH
    grade = getGrade(enable_md_flag = False)
    
    # write the case to handle the skipped reports #TODO - make sure that a regular user can't mark -2 on an original report
    if grade == -1: 
        # Ask the user for a reason
        skip_reason = getReason("skip")
        # Write a query to add the report to the skipped reports table. 
        # ('proc_ord_id', 'grade', 'grader_name', 'skip_date', 'skip_reason', 'regrade_date', 'regrade_reason')
        skipReportQuery = "insert into lab.skipped_reports values ("
        today = date.today().strftime("%Y-%m-%d")
        skipReportQuery += "'"+str(procOrdId)+"', "+str(grade)+", '"+name+"', '"+str(today)+"', '"+skip_reason+"', '', '');"
        
        # Execute the query
        # print(skipReportQuery)
        skipReportJob = client.query(skipReportQuery)
        skipReportJob.result()
        
        
    # LOH - do more changes need to be made here to change the metadata in the table? I think no but ...
    # Update the grader table with the new grade
    updateQuery = 'UPDATE lab.grader_table_with_metadata set grade = '+str(grade)
    today = date.today().strftime("%Y-%m-%d")
    updateQuery += ', grade_date = "'+today+'"'
    updateQuery += ' WHERE proc_ord_id = "'+str(df['proc_ord_id'].values[0])+'"' 
    updateQuery += ' and grader_name like "' + name + '"'

    updateJob = client.query(updateQuery)
    updateJob.result()
    print("Grade saved. Run the cell again to grade another report.")
    
##
# Get more proc_ord_id for which no reports have been rated for the specified user to grade
# @param name A str containing the full name of the grader (to also be referenced in publications)
def getMoreReportsToGrade(name, project_id="SLIP", numberToAdd=100):
    # Global var declaration
    global numUsersForValidation
    print("It is expected for this function to take several minutes to run. Your patience is appreciated.")
    
    # Initialize the client service
    client = bigquery.Client()  
    
    # Load the config file
    fn = "./queries/config.json" ## write this file
    with open(fn, "r") as f:
        project_lookup = json.load(f)
        
    # Get the info for the specified project
    project_info = project_lookup[project_id]
    queryFn = project_info['query']
    q_dx_filter = ''
    if 'dx_filter' in project_info:
        # Get the name of the dx filter file
        fn_dx_filter = project_info['dx_filter']
        # Expand the tilda for each user
        fn_dx_filter_full = os.path.expanduser(fn_dx_filter)
        # Convert the contents of the dx filter file to a sql query
        q_dx_filter = convertExcludeDxCsvToSql(fn_dx_filter_full)
    
    ## --- I think this was put into a function?
    # Open the specified query file
    with open(queryFn, 'r') as f:
        q_project = f.read()
        
    # If there is a dx filter, incorporate it into the loaded query
    if q_dx_filter != "":
        q_tmp = q_dx_filter + q_project.split("where")[0] 
        q_tmp += "left join exclude_table on proc_ord.pat_id = exclude_table.pat_id where exclude_table.pat_id is null and"
        q_tmp += q_project.split("where")[1]
        q_project = q_tmp
    ## ---
        
    # Run the query from the specified file -- should the query itself be passed to a dx filtering option?
    dfProject = client.query(q_project).to_dataframe()
    # Now we have the ids of the reports we want to grade for Project project
    projectProcIds = dfProject['proc_ord_id'].values 
    print("Number of ids for project", project_id, len(projectProcIds))
    
    # Get the proc_ord_ids from the grader table
    qGradeTable = "SELECT proc_ord_id, grader_name, project from lab.grader_table_with_metadata where grade_category='Unique' and project like '%"+project_id+"%' ; "
    dfGradeTable = client.query(qGradeTable).to_dataframe()
    gradeTableProcIds = dfGradeTable['proc_ord_id'].values
    userProcIds = dfGradeTable[dfGradeTable['grader_name'] == name]['proc_ord_id'].values
    
    # Validation: are there any reports for the project that need to be validated that name hasn't graded?
    toAddValidation = {}
    for procId in projectProcIds: # for each proc_id in the project
        if procId in dfGradeTable['proc_ord_id'].values: # if the proc_id report was already graded
            graders = dfGradeTable.loc[dfGradeTable['proc_ord_id'] == procId, "grader_name"].values
            gradersStr = ", ".join(graders)
            # if the report was not graded by Coarse Text Search or the user and has not been graded N times
            if "Coarse Text Search" not in gradersStr and name not in gradersStr and len(graders) < numUsersForValidation:
                toAddValidation[procId] = dfGradeTable.loc[dfGradeTable['proc_ord_id'] == procId, "project"].values[0]
            
    # projectReportsInTable = [procId for procId in projectProcIds if procId in dfGradeTable['proc_ord_id'].values and not dfGradeTable.loc[dfGradeTable['proc_ord_id'] == procId, "grader_name"].str.contains("Coarse Text Search").any() ]
    # Ignore procIds rated by User name
    print("Number of reports that need to be validated for "+project_id+":", len(toAddValidation))
    
    # Add validation reports - procIds already in the table
    countAdded = 0
    if len(toAddValidation) > 0:
        addReportsQuery = 'insert into lab.grader_table_with_metadata (proc_ord_id, grader_name, grade, grade_category, pat_id, age_in_days, proc_ord_year, proc_name, report_origin_table, project, grade_date) VALUES '
        for procId in toAddValidation:
            if countAdded < numberToAdd and procId not in userProcIds:
                row = dfProject[dfProject['proc_ord_id'] == procId]
                addReportsQuery += '("'+str(procId)+'", "'+name+'", 999, "Unique", "'
                addReportsQuery += row['pat_id'].values[0]+'", '+str(row['proc_ord_age'].values[0])
                addReportsQuery += ', '+str(row['proc_ord_year'].values[0])+', "'+str(row['proc_ord_desc'].values[0].replace("'", "\'"))
                addReportsQuery += '", "arcus.procedure_order", "'+toAddValidation[procId]+'", "0000-00-00"), '
                countAdded += 1
        addReportsQuery = addReportsQuery[:-2]+";"
        addingReports = client.query(addReportsQuery)
        addingReports.result()

    # New reports
    print("Number of validation reports added:", countAdded)
    toAddNew = [procId for procId in projectProcIds if procId not in dfGradeTable['proc_ord_id'].values][:(numberToAdd - countAdded)]
    
    # Add new reports
    print("Number of new reports to grade:", len(toAddNew))
    if len(toAddNew) > 0:
        addReportsQuery = 'insert into lab.grader_table_with_metadata (proc_ord_id, grader_name, grade, grade_category, pat_id, age_in_days, proc_ord_year, proc_name, report_origin_table, project, grade_date) VALUES '
        for procId in toAddNew:
            row = dfProject[dfProject['proc_ord_id'] == procId]
            addReportsQuery += '("'+str(procId)+'", "'+name+'", 999, "Unique", "'
            addReportsQuery += row['pat_id'].values[0]+'", '+str(row['proc_ord_age'].values[0])
            addReportsQuery += ', '+str(row['proc_ord_year'].values[0])+', "'+str(row['proc_ord_desc'].values[0].replace("'", "\'"))
            addReportsQuery += '", "arcus.procedure_order", "'+project_id+'", "0000-00-00"), '
        addReportsQuery = addReportsQuery[:-2]+";"
        addingReports = client.query(addReportsQuery)
        addingReports.result()
    
    # Check: how many reports were added for the user?
    if (len(toAddValidation) + len(toAddNew)) == 0:
        print("There are no reports returned by the specified query that have yet to be either graded or validated.")
    else:
        getUserUnratedCount = 'SELECT * FROM lab.grader_table_with_metadata WHERE grader_name like "' + name + '" and grade = 999'

        df = client.query(getUserUnratedCount).to_dataframe()

        # Inform the user
        print(len(df), "reports are in the queue for grader", name)
    
    
def welcomeUser(name):
    print("Welcome,", name)
   
    client = bigquery.Client()
    
    # Possibly pull this bit into its own function - make it user proof
    qCheckSelfEval = 'select * from lab.training_selfeval where grader_name like"'+name+'"'
    selfEvalDf = client.query(qCheckSelfEval).to_dataframe()
    
    if len(selfEvalDf) == 0:
        print("It appears you have yet to do the self-evaluation. Please grade those reports before continuing.")
        addSelfEvalReports(name)
        return
        
    elif 999 in selfEvalDf['grade'].values:
        print("It appears you have started the self-evaluation but have not finished it. Please grade those reports before continuing.")
        return
    
    qReliability = 'select * from lab.grader_table_with_metadata where grade_category = "Reliability" and grader_name like"'+name+'"'
    reliabilityDf = client.query(qReliability).to_dataframe()
           
    if not checkReliabilityRatings(reliabilityDf):       
        print("It appears you have yet to grade the reliability reports.")
        addReliabilityReports(name)
            
    elif 999 in reliabilityDf['grade'].values:
        reliabilityCount = len(reliabilityDf[reliabilityDf['grade'] == 999])
        print("You have", reliabilityCount, "reliability reports to grade.")
    
    else:
        getToRateCount = 'select * from lab.grader_table_with_metadata where grader_name like "'
        getToRateCount += name + '" and grade = 999'
        
        raterUnratedDf = client.query(getToRateCount).to_dataframe()
              
        if len(raterUnratedDf) == 0:
              print("You are caught up on your report ratings")
              # TODO add function here to get more reports for the user
        else:
              print("You currently have", len(raterUnratedDf), "ungraded reports to work on.")
                
    return True

            
def addReliabilityReports(name):
    client = bigquery.Client()
    
    # Get the grader table
    queryGetGraderTable = "SELECT * from lab.grader_table_with_metadata where grader_name = '"+name+"' and grade_category = 'Reliability';"
    graderDf = client.query(queryGetGraderTable).to_dataframe()
    
    reliabilityDf = pd.read_csv("~/arcus/shared/reliability_report_info.csv")
    addReports = False

    queryInsertReport = "INSERT into lab.grader_table_with_metadata (proc_ord_id, grader_name, grade, grade_category, pat_id, age_in_days, proc_ord_year, proc_name, report_origin_table, project, grade_date) VALUES"
    
    # print(graderDf['proc_ord_id'].values)

    for idx, row in reliabilityDf.iterrows():
        # print(row['proc_ord_id'])
        if str(row['proc_ord_id']) not in graderDf['proc_ord_id'].values:
            # Add the report
            queryInsertReport += " ('"+str(int(row['proc_ord_id']))+"', '"+name+"', 999, 'Reliability', '"
            queryInsertReport += row['pat_id']+"', "+str(row['age_in_days'])+", "+str(row['proc_ord_year'])+", '"
            queryInsertReport += row['proc_name']+"', '"+row['report_origin_table']+"', '"+row['project']
            queryInsertReport += "', '0000-00-00'),"
            addReports = True

    if addReports:
        print("Adding reliability reports to grade")
        queryInsertReport = queryInsertReport[:-1] + ";"
        # print(queryInsertReport)
        addReportJob = client.query(queryInsertReport)
        addReportJob.result()
        
            
def checkReliabilityRatings(graderDf):
        
    if len(graderDf) == 0:
        return False
    
    name = graderDf['grader_name'].values[0]
    reliabilityDf = pd.read_csv("~/arcus/shared/reliability_report_info.csv")
    reliabilityIds = reliabilityDf['proc_ord_id'].values
    graderReliabilityDf = graderDf[graderDf['grade_category'] == 'Reliability']
    graderIds = graderReliabilityDf['proc_ord_id'].values
    numReliability = len([i for i in reliabilityIds if str(i) in graderIds])
    # numGradedReliability = len(graderReliabilityDf[graderReliabilityDf['grade'] != 999]['proc_ord_id'].values)
    numGradedReliability = len([i for i in reliabilityIds if str(i) in graderIds and max(graderReliabilityDf[graderReliabilityDf['proc_ord_id'] == str(i)]['grade'].values) != 999]) 
    
    print(numReliability)
    print(len(reliabilityIds))
    assert numReliability == len(reliabilityIds)
    print(name, "has graded", numGradedReliability, "of", numReliability, "reliability reports")
    
    if numGradedReliability == numReliability:
        return True
    elif numGradedReliability < numReliability:
        return False
    else:
        print("Error (code surplus): Grader has graded more reliability reports than exist")
        
        
        
##
# For a specified list of reports, change their grades to 999 to put them back
# in a user's queue. ASSUMES THE USER HAS VERIFIED THE REPORTS TO RELEASE
# @param graderName A string specifying the grader
# @param reportsList A list of proc_ord_id elements to reset the grades for
def releaseReports(graderName, reportsList):
    # Initialize the client
    client = bigquery.Client()

    # For each report
    for procId in reportsList:
        # Update the grader table with the new grade
        updateQuery = 'UPDATE lab.grader_table_with_metadata set grade = 999,'
        updateQuery += ' grade_date="0000-00-00"'
        updateQuery += ' WHERE proc_ord_id = "'+str(procId)+'"'
        updateQuery += ' and grader_name = "' + graderName + '"'

        updateJob = client.query(updateQuery)
        updateJob.result()
        
    print(len(reportsList), "were released back into the queue for", graderName)
    
    
# LOH How do I test this?
# Create a user Bob Belcher
# Add the reliability reports
# Grade some of his reliability reports
# Back up his grades
# Check
# Grade more
# Back up his grades again
# Check
def backupReliabilityGrades(user):
    client = bigquery.Client()
    
    q = "select * from lab.grader_table_with_metadata where grader_name = '"+user
    q += "' and grade_category = 'Reliability'"
    primaryDf = client.query(q).to_dataframe()
    
    for procId in primaryDf['proc_ord_id'].values:
        # If the proc id is not in the df for the user
        q = "select * from lab.reliability_grades_original where grader_name = '"+user
        q += "' and grade_category = 'Reliability' and proc_ord_id = " + str(procId) + ";"
        backupDf = client.query(q).to_dataframe()
        
        # if the query returned an empty dataframe
        if len(backupDf) == 0:
            # Then add the row to the table
            addQ = "insert into lab.reliability_grades_original (proc_ord_id, grader_name, "
            addQ += "grade, grade_category, pat_id, age_in_days, proc_ord_year, proc_name, "
            addQ += "report_origin_table, project) values ('"+str(procId)+"', '"+primaryDf['grader_name'].values[0]
            addQ += "', "+str(primaryDf['grade'].values[0])+", 'Reliability', '"+str(primaryDf['pat_id'].values[0])
            addQ += "', "+str(primaryDf['age_in_days'].values[0])+", "+str(primaryDf['proc_ord_year'].values[0])
            addQ += ", '"+str(primaryDf['proc_name'].values[0])+"', '"+str(primaryDf['report_origin_table'].values[0])
            addQ += "', '"+str(primaryDf['project'].values[0])+"', '"+str(primaryDf['grade_date'].values[0])+"' ) ;"
            
            # addJob = client.query(addQ)
            # addJob.result()
            
            
        elif len(backupDf) == 1:
            if backupDf['grade'].values == 999:
                updateQ = 'UPDATE lab.reliability_grades_original set grade = '+primaryDf['grade'].values[0]
                updateQ += ' WHERE proc_ord_id = "'+str(primaryDf['proc_ord_id'].values[0])+'"'
                updateQ += ' and grader_name = "' + str(primaryDf['grader_name'].values[0])+'"'
                
                updateJob = client.query(updateQ)
                updateJob.result()
                

def printReport(procId, client, toHighlight={}, sourceTable="arcus.procedure_order_narrative"):
    print(sourceTable)
    try: 
        # Get the report for that proc_ord_id from the primary report table
        getReportRow = 'SELECT * FROM '+ sourceTable+' where proc_ord_id like "'+str(procId)+'"'
        reportDf = client.query(getReportRow).to_dataframe()
    except:
        print("AN ERROR HAS OCCURRED: REPORT", procId, "CANNOT BE FOUND IN", sourceTable)
    
    # If the id was in the new table:
    if len(reportDf) == 1:
        originTable = sourceTable
        domain = sourceTable.split(".")[0]
        
        getReportRow = 'SELECT * FROM '+domain+'.procedure_order_narrative where proc_ord_id = "'+str(procId)+'"'
        reportText = client.query(getReportRow).to_dataframe()['narrative_text'].values[0]
        
        getReportRow = 'SELECT * FROM '+domain+'.procedure_order_impression where proc_ord_id = "'+str(procId)+'"'
        reportDf = client.query(getReportRow).to_dataframe()
        
        if len(reportDf) == 1:
            reportText += "\n\nIMPRESSION: " + reportDf['impression_text'].values[0]
            
    elif len(reportDf) == 0:
        print("proc_ord_id not in", sourceTable, ":", procId)   

    reportText = " ".join(reportText.split())
    reportText = reportText.replace("CLINICAL INDICATION", "\n\nCLINICAL INDICATION")
    reportText = reportText.replace("TECHNIQUE", "\n\nTECHNIQUE")
    reportText = reportText.replace("HISTORY", "\n\nHISTORY")
    reportText = reportText.replace("IMPRESSION", "\n\nIMPRESSION")
    reportText = reportText.replace("FINDINGS", "\n\nFINDINGS")
    reportText = reportText.replace("COMPARISON", "\n\nCOMPARISON")
    
    # If the user passed a dictionary of lists to highlight
    if len(toHighlight.keys()) > 0:
        for key in toHighlight.keys():
            reportText = markTextColor(reportText, toHighlight[key], key)
            
    # Print the report and ask for a grade
    print(reportText)
    print()
    # Print the proc_ord_id
    print("Report id:", str(procId))
    print()
    
    
def getReason(usage):
    if usage == "skip":
        message = "This report was skipped. Please include the part(s) of the report that were confusing:"
    elif usage == "regrade":
        message = "This report was previously skipped. Please include an explanation why it received its updated grade:"
        
    reason = str(input(message))
    while type(reason) != str and len(reason) <= 5: #arbitrary minimum string length
        reason = str(input(message))
        
    return reason


def getGrade(enable_md_flag = False):
        
    if enable_md_flag:
        potential_grades = ["0", "1", "2", "-1", "-2"]
        grade = str(input('Assign a SLIP rating to this report (0 do not use/1 maybe use/2 definitely use/-1 skip/-2 escalate to clinician): '))

    else:
        potential_grades = ["0", "1", "2", "-1"]
        grade = str(input('Assign a SLIP rating to this report (0 do not use/1 maybe use/2 definitely use/-1 skip): '))

    while grade not in potential_grades:
        if not enable_md_flag:
            if grade == "-2":
                print("Reports cannot be marked for clinician review without undergoing peer review first. Please flag using a grade of -1 instead.")
                message = "Please enter a grade value from the acceptable grade list (0/1/2/-1): "
                grade = str(input(message))
            else:
                grade = str(input('Invalid input. Assign a SLIP rating to this report (0 do not use/1 maybe use/2 definitely use/-1 skip): '))
        else:
            grade = str(input('Invalid input. Assign a SLIP rating to this report (0 do not use/1 maybe use/2 definitely use/-1 skip/-2 escalate to MD): '))

            
    print()
    
    # Ask the user to confirm the grade
    confirmGrade = "999"
    while confirmGrade != grade :
        while confirmGrade not in potential_grades:
            if not enable_md_flag and confirmGrade == "-2":
                print("Reports cannot be marked for clinician review without undergoing peer review first. Please flag using a grade of -1 instead.")
                message = "Please enter a grade value from the acceptable grade list (0/1/2/-1): "
            else:
                message = "Please confirm your grade by reentering it OR enter a revised value to change the grade: "
            confirmGrade = str(input(message))
        if confirmGrade != grade:
            if not enable_md_flag and confirmGrade == "-2":
                print("Reports cannot be marked for clinician review without undergoing peer review first. Please flag using a grade of -1 instead.")
                message = "Please enter a grade value from the acceptable grade list (0/1/2/-1): "
                confirmGrade = str(input(message))
            else:
                grade = confirmGrade
                confirmGrade = "999"
    
    if confirmGrade == "-1":
        print("This report is being marked as SKIPPED (-1) for you.")
        return -1
    elif confirmGrade == "-2": 
        print("WARNING: this report is being marked as SKIPPED for you AND is being escalated to a clinician for further review.")
        return -2
    else:
        print("Saving your grade of", grade, "for this report.")
        return grade
    

def getGraderStatusReport(name):
    client = bigquery.Client()
    
    query = "select * from lab.grader_table_with_metadata where "
    query += "grader_name = '"+ name +"';"
    print(query)
    df = client.query(query).to_dataframe()
    
    # Case: user not in table
    if len(df) == 0:
        print("User is not in the table yet.")
        return
    
    # Reliability ratings
    checkReliabilityRatings(df)
    
    # Unique
    uniqueReportsDf = df[df['grade_category'] == 'Unique']
    gradedUniqueReportsDf = df[(df['grade_category'] == 'Unique') & (df['grade'] != 999)]
    print(name, "has graded", gradedUniqueReportsDf.shape[0], "unique reports of", uniqueReportsDf.shape[0], "assigned where")
    for grade in range(3):
        numGraded = gradedUniqueReportsDf[gradedUniqueReportsDf['grade'] == grade].shape[0]
        print(numGraded, "have been given a grade of", grade)
        
        
        

        
            
# Main
if __name__ == "__main__":

    print("Radiology Report Annotation Helper Library v 0.2")
    print("Written and maintained by Jenna Young, PhD (@jmschabdach on Github)")
    print("Tested and used by:")
    print("- Caleb Schmitt, Summer 2021")
    print("- Nadia Ngom, Fall 2021 - Spring 2022")
    print("- Alesandra Gorgone, Spring 2023")

