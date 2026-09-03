/**
 * @name VIPER Python dependencies
 * @description Emits resolved call and construction dependencies between Python declarations.
 * @kind table
 * @id viper/python-impact/dependencies
 */

import python
import LegacyPointsTo
import semmle.python.objects.ObjectAPI
import semmle.python.dependencies.DependencyKind

predicate dependency(AstNode source, AstNode target, string kind, AstNode evidence) {
  exists(Call call, FunctionValue function |
    evidence = call and
    source = call.getScope() and
    call.getFunc().(ExprWithPointsTo).pointsTo(function) and
    target = function.getScope() and
    kind = "calls"
  )
  or
  exists(Call call, ClassValue cls |
    evidence = call and
    source = call.getScope() and
    call.getFunc().(ExprWithPointsTo).pointsTo(cls) and
    target = cls.getScope() and
    kind = "constructs"
  )
  or
  exists(Class subclass, Expr base, ClassValue superclass |
    evidence = base and
    source = subclass and
    base = subclass.getABase() and
    base.(ExprWithPointsTo).pointsTo(superclass) and
    target = superclass.getScope() and
    kind = "inherits"
  )
  or
  exists(DependencyKind dependencyKind, AstNode use, Object object |
    evidence = use and
    dependencyKind.isADependency(use, object) and
    target = object.getOrigin() and
    (
      use instanceof ImportingStmt and source = use
      or
      not use instanceof ImportingStmt and source = use.getScope()
    ) and
    (
      dependencyKind = "import" and kind = "imports"
      or
      dependencyKind = "inheritance" and kind = "inherits"
      or
      dependencyKind in ["use", "attribute"] and kind = "reads"
    )
  )
}

from AstNode source, AstNode target, string kind, AstNode evidence
where
  dependency(source, target, kind, evidence) and
  source.getLocation().getFile() = evidence.getLocation().getFile() and
  not target.getLocation().getFile().getRelativePath() = ""
select source.getLocation().getFile().getRelativePath(),
  source.getLocation().getStartLine(), source.getLocation().getStartColumn(),
  target.getLocation().getFile().getRelativePath(),
  target.getLocation().getStartLine(), target.getLocation().getStartColumn(),
  kind, evidence.getLocation().getFile().getRelativePath(),
  evidence.getLocation().getStartLine()
