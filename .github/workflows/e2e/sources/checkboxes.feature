Feature: Checkboxes through a real browser

Scenario: A filer checks two fruits and sees them gathered
  Given I start the interview at "http://localhost:8080/interview?i=docassemble.demo:data/questions/test_issue_981.yml"
  And I set the var "fruit['apple']" to "True"
  And I set the var "fruit['cherry']" to "True"
  # ALKiln's "I tap to continue" looks for fieldset.da-field-buttons, but
  # docassemble 1.10.8 replaced that fieldset with a div, so tap by selector.
  And I tap the ".da-field-buttons button[type='submit'].btn-primary" element and go to the next page
  Then I should see the phrase "You chose apple and cherry."
