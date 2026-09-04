/**
 * @name VIPER Python declarations
 * @description Emits Python declarations used by the System Impact source graph.
 * @kind table
 * @id viper/python-impact/declarations
 */

import python
import Nodes

from AstNode node, AstNode binding, string kind, string name
where declaration(node, binding, kind, name)
select node.getLocation().getFile().getRelativePath(), name, kind,
  binding.getLocation().getStartLine(), binding.getLocation().getStartColumn()
