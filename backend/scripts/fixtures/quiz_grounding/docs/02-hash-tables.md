# Hash Tables

A hash table is a data structure that maps keys to values using a hash function to compute an index into an array of buckets. A good hash function distributes keys uniformly across the buckets, minimizing the chance that two different keys map to the same index.

When two distinct keys do map to the same bucket, this event is called a collision, and the hash table must handle it. One approach resolves collisions through separate chaining, which stores a linked list of entries at each bucket so multiple keys can coexist at the same index. Another approach, open addressing, instead resolves collisions by probing for the next available slot in the array itself, using strategies such as linear probing or double hashing.

The load factor of a hash table is the ratio of stored entries to the number of buckets. As the load factor grows, collisions become more frequent and operations slow down, so most implementations trigger a resize once the load factor crosses a threshold, allocating a larger backing array and rehashing every existing entry into it.

With a well-chosen hash function and a reasonable load factor, insertion, deletion, and lookup in a hash table all run in expected constant time, even though a poorly designed hash function can degrade performance to linear time in the worst case.
