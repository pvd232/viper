/**
 * @name VIPER Python dependencies
 * @description Emits typed dependencies between repository Python declarations.
 * @kind table
 * @id viper/python-impact/dependencies
 */

import python
import LegacyPointsTo
import semmle.python.objects.ObjectAPI
import semmle.python.dependencies.DependencyKind

/**
 * Select an assignment that defines a module or class variable represented by
 * SourceNode.
 */
private predicate declarationAssignment(Variable variable, AstNode target) {
  (
    variable.getScope() instanceof Module
    or
    variable.getScope() instanceof Class
  ) and
  (
    exists(Assign assignment, Name name |
      target = assignment and
      assignment.getScope() = variable.getScope() and
      name = assignment.getATarget() and
      name.getVariable() = variable
    )
    or
    exists(AnnAssign assignment, Name name |
      target = assignment and
      assignment.getScope() = variable.getScope() and
      name = assignment.getTarget() and
      name.getVariable() = variable
    )
  )
}

/** Return whether `later` occurs strictly after `earlier` in one source file. */
private predicate occursAfter(AstNode later, AstNode earlier) {
  later.getLocation().getFile() = earlier.getLocation().getFile() and
  (
    later.getLocation().getStartLine() >
      earlier.getLocation().getStartLine()
    or
    later.getLocation().getStartLine() =
      earlier.getLocation().getStartLine() and
    later.getLocation().getStartColumn() >
      earlier.getLocation().getStartColumn()
  )
}

/**
 * Select the final module or class assignment for one variable. This matches
 * the canonical assignment selected by VIPER's source-node lowerer.
 */
private predicate canonicalAssignment(Variable variable, AstNode target) {
  declarationAssignment(variable, target) and
  not exists(AstNode later |
    declarationAssignment(variable, later) and
    occursAfter(later, target)
  )
}

/**
 * Match a direct name write such as a function assigning to a declared global.
 */
private predicate directNameWrite(
  AstNode source,
  AstNode target,
  AstNode evidence
) {
  exists(Name store, Variable variable |
    store = variable.getAStore() and
    source = store.getScope() and
    canonicalAssignment(variable, target) and
    evidence = store
  )
}

/**
 * Resolve a direct attribute store to its declaring class when CodeQL knows
 * the receiver class.
 */
private predicate attributeOwner(
  Attribute store,
  Class owner,
  string name
) {
  exists(SelfAttributeStore selfStore |
    store = selfStore and
    owner = selfStore.getClass() and
    name = selfStore.getName()
  )
  or
  exists(AttrNode cfg, ClassObject classObject |
    cfg.getNode() = store and
    cfg.isStore() and
    name = store.getName() and
    cfg.getObject(name)
      .(ControlFlowNodeWithPointsTo)
      .refersTo(_, classObject, _) and
    owner = classObject.getPyClass()
  )
}

/**
 * Match a direct attribute write whose class attribute already has a canonical
 * assignment SourceNode.
 */
private predicate directAttributeWrite(
  AstNode source,
  AstNode target,
  AstNode evidence
) {
  exists(Attribute store, Class owner, string name, Variable variable |
    attributeOwner(store, owner, name) and
    variable.getScope() = owner and
    variable.getId() = name and
    canonicalAssignment(variable, target) and
    source = store.getScope() and
    evidence = store
  )
}

predicate dependency(
  AstNode source,
  AstNode target,
  string kind,
  AstNode evidence
) {
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
  or
  (
    directNameWrite(source, target, evidence)
    or
    directAttributeWrite(source, target, evidence)
  ) and
  kind = "writes"
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
