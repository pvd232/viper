/**
 * @name VIPER Python dependencies
 * @description Emits typed dependencies between repository Python declarations.
 * @kind table
 * @id viper/python-impact/dependencies
 */

import python
import LegacyPointsTo
import Nodes
import semmle.python.objects.ObjectAPI

/**
 * Find the nearest represented declaration that contains dependency evidence.
 * This keeps calls inside comprehensions attached to their enclosing function.
 */
private predicate dependencySource(AstNode evidence, AstNode source) {
  source.contains(evidence) and
  exists(AstNode binding, string kind, string name |
    declaration(source, binding, kind, name)
  ) and
  not exists(AstNode nearer, AstNode binding, string kind, string name |
    nearer.contains(evidence) and
    source.contains(nearer) and
    source != nearer and
    declaration(nearer, binding, kind, name)
  )
}

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
    dependencySource(store, source) and
    canonicalAssignment(variable, target) and
    evidence = store
  )
}

/** Match a direct read of a declared module or class variable. */
private predicate directNameRead(
  AstNode source,
  AstNode target,
  AstNode evidence
) {
  exists(Name load, Variable variable |
    load = variable.getALoad() and
    dependencySource(load, source) and
    canonicalAssignment(variable, target) and
    evidence = load
  )
}

/** Resolve an attribute read to its declaring class. */
private predicate attributeReadOwner(
  Attribute load,
  Class owner,
  string name
) {
  exists(SelfAttributeRead selfRead |
    load = selfRead and
    owner = selfRead.getClass() and
    name = selfRead.getName()
  )
  or
  exists(AttrNode cfg, ClassObject classObject |
    cfg.getNode() = load and
    cfg.isLoad() and
    name = load.getName() and
    cfg.getObject(name)
      .(ControlFlowNodeWithPointsTo)
      .refersTo(_, classObject, _) and
    owner = classObject.getPyClass()
  )
}

/** Resolve an attribute write to its declaring class. */
private predicate attributeWriteOwner(
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

/** Match a direct read of a declared class attribute. */
private predicate directAttributeRead(
  AstNode source,
  AstNode target,
  AstNode evidence
) {
  exists(Attribute load, Class owner, string name, Variable variable |
    attributeReadOwner(load, owner, name) and
    variable.getScope() = owner and
    variable.getId() = name and
    canonicalAssignment(variable, target) and
    dependencySource(load, source) and
    evidence = load
  )
}

/** Match one `from module import name` with that module's named declaration. */
private predicate directImport(
  AstNode source,
  AstNode sourceBinding,
  AstNode target,
  AstNode targetBinding,
  AstNode evidence
) {
  exists(
    Import statement, Alias imported, ImportMember member,
    string sourceKind, string sourceName, string targetKind, string targetName
  |
    source = statement and
    imported = statement.getAName() and
    member = imported.getValue() and
    sourceBinding = member and
    declaration(source, sourceBinding, sourceKind, sourceName) and
    declaration(target, targetBinding, targetKind, targetName) and
    targetName = member.getName() and
    target.getScope().getEnclosingModule().getName() =
      member.getModule().(ImportExpr).getImportedModuleName() and
    evidence = member
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
    attributeWriteOwner(store, owner, name) and
    variable.getScope() = owner and
    variable.getId() = name and
    canonicalAssignment(variable, target) and
    dependencySource(store, source) and
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
    dependencySource(call, source) and
    call.getFunc().(ExprWithPointsTo).pointsTo(function) and
    target = function.getScope() and
    kind = "calls"
  )
  or
  exists(Call call, ClassValue cls |
    evidence = call and
    dependencySource(call, source) and
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
  (
    directNameRead(source, target, evidence)
    or
    directAttributeRead(source, target, evidence)
  ) and
  kind = "reads"
  or
  (
    directNameWrite(source, target, evidence)
    or
    directAttributeWrite(source, target, evidence)
  ) and
  kind = "writes"
}

from AstNode source, AstNode sourceBinding, AstNode target, AstNode targetBinding,
  string sourceKind, string sourceName, string targetKind, string targetName,
  string kind, AstNode evidence
where
  (
    dependency(source, target, kind, evidence) and
    declaration(source, sourceBinding, sourceKind, sourceName) and
    declaration(target, targetBinding, targetKind, targetName)
    or
    directImport(source, sourceBinding, target, targetBinding, evidence) and
    kind = "imports" and
    declaration(source, sourceBinding, sourceKind, sourceName) and
    declaration(target, targetBinding, targetKind, targetName)
  ) and
  source.getLocation().getFile() = evidence.getLocation().getFile() and
  not target.getLocation().getFile().getRelativePath() = ""
select source.getLocation().getFile().getRelativePath(),
  sourceBinding.getLocation().getStartLine(), sourceBinding.getLocation().getStartColumn(),
  target.getLocation().getFile().getRelativePath(),
  targetBinding.getLocation().getStartLine(), targetBinding.getLocation().getStartColumn(),
  kind, evidence.getLocation().getFile().getRelativePath(),
  evidence.getLocation().getStartLine(), evidence.getLocation().getStartColumn()
