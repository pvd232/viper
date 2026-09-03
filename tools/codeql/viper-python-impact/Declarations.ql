/**
 * @name VIPER Python declarations
 * @description Emits Python declarations used by the System Impact source graph.
 * @kind table
 * @id viper/python-impact/declarations
 */

import python

predicate declaration(AstNode node, string kind, string name) {
  exists(Function function |
    node = function and
    name = function.getName() and
    (
      function.getScope() instanceof Class and kind = "method"
      or
      not function.getScope() instanceof Class and kind = "function"
    )
  )
  or
  exists(Class cls | node = cls and name = cls.getName() and kind = "class")
  or
  exists(Assign assignment, Name target |
    node = assignment and
    target = assignment.getATarget() and
    name = target.getId() and
    kind = "assignment"
  )
  or
  exists(AnnAssign assignment, Name target |
    node = assignment and
    target = assignment.getTarget() and
    name = target.getId() and
    kind = "assignment"
  )
  or
  exists(Import statement, Alias imported |
    node = statement and
    imported = statement.getAName() and
    name = imported.toString() and
    kind = "import"
  )
}

from AstNode node, string kind, string name
where declaration(node, kind, name)
select node.getLocation().getFile().getRelativePath(), name, kind,
  node.getLocation().getStartLine(), node.getLocation().getStartColumn(),
  node.getLocation().getEndLine(), node.getLocation().getEndColumn()
