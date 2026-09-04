import python

/** Keep module declarations and declarations nested only through classes. */
private predicate representedScope(Scope scope) {
  scope instanceof Module
  or
  exists(Class owner |
    scope = owner and
    representedScope(owner.getScope())
  )
}

/** Return the name VIPER uses for a module or class assignment. */
private string assignmentName(Name target) {
  target.getScope() instanceof Module and
  result = target.getId()
  or
  exists(Class owner |
    owner = target.getScope() and
    representedScope(owner) and
    result = owner.getQualifiedName() + "." + target.getId()
  )
}

/** Return the local name created by one import. */
private predicate explicitAlias(Alias imported, Name alias) {
  alias = imported.getAsname() and
  (
    alias.getLocation().getStartLine() != imported.getValue().getLocation().getStartLine()
    or
    alias.getLocation().getStartColumn() != imported.getValue().getLocation().getStartColumn()
    or
    alias.getLocation().getEndLine() != imported.getValue().getLocation().getEndLine()
    or
    alias.getLocation().getEndColumn() != imported.getValue().getLocation().getEndColumn()
  )
}

/** Return the name VIPER uses for one import declaration. */
private string importName(Alias imported) {
  exists(Name alias |
    explicitAlias(imported, alias) and
    result = alias.getId()
  )
  or
  not exists(Name alias | explicitAlias(imported, alias)) and
  exists(ImportExpr importedModule |
    importedModule = imported.getValue() and
    result = importedModule.getName()
  )
  or
  not exists(Name alias | explicitAlias(imported, alias)) and
  exists(ImportMember member |
    member = imported.getValue() and
    result = member.getName()
  )
}

/**
 * Identify one declaration and the exact source occurrence that binds its
 * name. The binding location is the join key used by the Python AST loader.
 */
predicate declaration(
  AstNode node,
  AstNode binding,
  string kind,
  string name
) {
  exists(Function function |
    node = function and binding = function and
    function.getDefinition() instanceof FunctionExpr and
    name = function.getQualifiedName() and
    representedScope(function.getEnclosingScope()) and
    (
      function.getScope() instanceof Class and kind = "method"
      or
      not function.getScope() instanceof Class and kind = "function"
    )
  )
  or
  exists(Class cls |
    node = cls and binding = cls and
    name = cls.getQualifiedName() and kind = "class" and
    representedScope(cls.getScope())
  )
  or
  exists(Assign assignment, Name target |
    not assignment instanceof FunctionDef and
    not assignment instanceof ClassDef and
    node = assignment and binding = target and
    target = assignment.getATarget() and
    name = assignmentName(target) and
    kind = "assignment"
  )
  or
  exists(AnnAssign assignment, Name target |
    node = assignment and binding = target and
    target = assignment.getTarget() and
    name = assignmentName(target) and
    kind = "assignment"
  )
  or
  exists(Import statement, Alias imported |
    node = statement and binding = imported.getValue() and
    imported = statement.getAName() and
    name = importName(imported) and
    kind = "import" and
    representedScope(statement.getScope())
  )
}
