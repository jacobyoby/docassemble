Feature: Checkboxes through a real browser

Scenario: A filer checks two fruits and sees them gathered
  Given I start the interview at "http://localhost:8080/interview?i=docassemble.demo:data/questions/test_issue_981.yml"
  And I set the var "fruit['apple']" to "True"
  And I set the var "fruit['cherry']" to "True"
  And I tap to continue
  Then I should see the phrase "You chose apple and cherry."
