package com.tripledger.common;

public record Actor(
    String id, String email, String name, String role, String managerId, boolean active) {
  public boolean admin() {
    return role.equals("ADMIN");
  }

  public boolean manager() {
    return role.equals("MANAGER");
  }

  public void require(String expected) {
    if (!role.equals(expected)) throw ApiError.forbidden();
  }
}
