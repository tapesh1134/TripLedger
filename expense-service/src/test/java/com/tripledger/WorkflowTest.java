package com.tripledger;

import static org.junit.jupiter.api.Assertions.*;

import com.tripledger.common.*;
import java.util.*;
import org.junit.jupiter.api.Test;

class WorkflowTest {
  final ExpenseController controller = new ExpenseController(null, null, null, "", "");
  Actor employee = new Actor("employee", "e@example.test", "Employee", "EMPLOYEE", "manager", true);
  Actor manager = new Actor("manager", "m@example.test", "Manager", "MANAGER", null, true);

  Map<String, Object> report() {
    return new HashMap<>(
        Map.of(
            "employee_id",
            "employee",
            "manager_id",
            "manager",
            "status",
            "DRAFT",
            "row_version",
            2));
  }

  @Test
  void employeeCannotReadOtherReports() {
    var r = report();
    r.put("employee_id", "someone-else");
    assertThrows(ApiError.class, () -> controller.access(employee, r));
  }

  @Test
  void assignedManagerCanRead() {
    assertDoesNotThrow(() -> controller.access(manager, report()));
  }

  @Test
  void unrelatedManagerCannotRead() {
    var r = report();
    r.put("manager_id", "another-manager");
    assertThrows(ApiError.class, () -> controller.access(manager, r));
  }

  @Test
  void staleEditIsRejected() {
    assertThrows(ApiError.class, () -> controller.edit(employee, report(), 1));
  }

  @Test
  void submittedReportCannotBeEdited() {
    var r = report();
    r.put("status", "SUBMITTED");
    assertThrows(ApiError.class, () -> controller.edit(employee, r, 2));
  }

  @Test
  void managerCannotApproveOwnReport() {
    var r = report();
    r.put("employee_id", "manager");
    assertThrows(ApiError.class, () -> controller.manager(manager, r));
  }

  @Test
  void clarificationCanBeEditedByOwner() {
    var r = report();
    r.put("status", "CLARIFICATION");
    assertDoesNotThrow(() -> controller.edit(employee, r, 2));
  }
}
